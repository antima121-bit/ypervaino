from __future__ import annotations

import math
import random
from collections import defaultdict
from typing import Any

from ypervaino.embeddings import cosine_distance, embedding_dim, farthest_point_indices, medoid_index
from ypervaino.features import stratum_key
from ypervaino.sampling import _allocate_quotas


def _items(session_ids: list[str], features: dict[str, dict[str, Any]]) -> list[tuple[str, dict]]:
    out = []
    for sid in session_ids:
        fv = features.get(sid)
        if fv and int(fv.get("turn_count") or 0) >= 2:
            out.append((sid, fv))
    return out


def _pick_from_stratum(pool: list[tuple[str, dict]], quota: int) -> list[str]:
    if quota <= 0 or not pool:
        return []
    if len(pool) <= quota:
        return [sid for sid, _ in pool]
    zero = [0.0] * embedding_dim()
    vectors = [fv.get("embedding_opening") or zero for _, fv in pool]
    k = min(quota, max(1, int(math.ceil(math.sqrt(len(pool))))))
    idxs = farthest_point_indices(vectors, k, seed=[medoid_index(vectors)])
    if len(idxs) < quota:
        remaining = [i for i in range(len(pool)) if i not in idxs]
        random.shuffle(remaining)
        idxs.extend(remaining[: quota - len(idxs)])
    return [pool[i][0] for i in idxs[:quota]]


def sample_single_cohort(session_ids: list[str], features: dict[str, dict], n_explore: int) -> list[str]:
    items = _items(session_ids, features)
    if not items:
        return []
    strata: dict[tuple, list[tuple[str, dict]]] = defaultdict(list)
    for sid, fv in items:
        strata[stratum_key(fv)].append((sid, fv))
    quotas = _allocate_quotas({k: [x[0] for x in v] for k, v in strata.items()}, n_explore)
    quotas = dict(sorted(quotas.items(), key=lambda kv: len(strata[kv[0]])))
    picked: list[str] = []
    for sk, quota in quotas.items():
        picked.extend(_pick_from_stratum(strata[sk], quota))
    if len(picked) < n_explore:
        rest = [sid for sid, _ in items if sid not in picked]
        random.shuffle(rest)
        picked.extend(rest[: n_explore - len(picked)])
    return picked[:n_explore]


def sample_comparative_pairs(
    before_ids: list[str],
    after_ids: list[str],
    features: dict[str, dict],
    n_explore: int,
    pairing_turn_tolerance: int = 3,
) -> dict[str, Any]:
    n_pairs = max(1, n_explore // 2)
    before_items = _items(before_ids, features)
    after_items = _items(after_ids, features)
    if not before_items or not after_items:
        return {"pairs": [], "session_ids": [], "by_cohort": {"before": [], "after": []}}

    before_strata: dict[tuple, list] = defaultdict(list)
    for sid, fv in before_items:
        before_strata[stratum_key(fv)].append((sid, fv))
    quotas = _allocate_quotas({k: [x[0] for x in v] for k, v in before_strata.items()}, n_pairs)
    quotas = dict(sorted(quotas.items(), key=lambda kv: len(before_strata[kv[0]])))

    selected_before: list[tuple[str, dict]] = []
    used_strata = set()
    for sk, quota in quotas.items():
        picks = _pick_from_stratum(before_strata[sk], quota)
        for sid in picks:
            fv = features[sid]
            selected_before.append((sid, fv))
            used_strata.add(sk)

    after_by_stratum: dict[tuple, list] = defaultdict(list)
    for sid, fv in after_items:
        after_by_stratum[stratum_key(fv)].append((sid, fv))

    pairs = []
    used_after = set()
    for b_sid, b_fv in selected_before[:n_pairs]:
        sk = stratum_key(b_fv)
        pool = after_by_stratum.get(sk) or after_items
        best = None
        best_d = 1e9
        b_turns = int(b_fv.get("turn_count") or 0)
        zero = [0.0] * embedding_dim()
        b_emb = b_fv.get("embedding_opening") or zero
        for a_sid, a_fv in pool:
            if a_sid in used_after:
                continue
            if abs(int(a_fv.get("turn_count") or 0) - b_turns) > pairing_turn_tolerance:
                continue
            if str(a_fv.get("outcome_bucket")) != str(b_fv.get("outcome_bucket")):
                continue
            d = cosine_distance(b_emb, a_fv.get("embedding_opening") or zero)
            if d < best_d:
                best_d, best = d, (a_sid, a_fv)
        if best:
            used_after.add(best[0])
            pairs.append({"before": b_sid, "after": best[0], "stratum": sk})

    flat_before = [p["before"] for p in pairs]
    flat_after = [p["after"] for p in pairs]
    return {
        "pairs": pairs,
        "session_ids": flat_before + flat_after,
        "by_cohort": {"before": flat_before, "after": flat_after},
    }


def build_exploration_manifest(
    study_type: str,
    session_ids: dict[str, list[str]],
    features: dict[str, dict],
    n_explore: int,
    pairing_turn_tolerance: int = 3,
) -> dict[str, Any]:
    if study_type == "comparative":
        manifest = sample_comparative_pairs(
            session_ids.get("before") or [],
            session_ids.get("after") or [],
            features,
            n_explore,
            pairing_turn_tolerance,
        )
    else:
        ids = sample_single_cohort(session_ids.get("all") or [], features, n_explore)
        manifest = {"pairs": [], "session_ids": ids, "by_cohort": {"all": ids}}
    manifest["n_explore"] = n_explore
    manifest["study_type"] = study_type
    return manifest
