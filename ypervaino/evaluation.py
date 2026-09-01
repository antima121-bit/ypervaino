from __future__ import annotations

import random
import statistics
from collections import defaultdict
from typing import Any

from scipy import stats

from ypervaino.hypothesis_predicate import normalize_hypothesis_predicate
from ypervaino.embeddings import cosine_distance
from ypervaino.parallel import run_parallel, worker_count
from ypervaino.signals import SignalExecutor, eval_hypothesis


def _aggregate(values: list[float], aggregation: str) -> float:
    if not values:
        return 0.0
    if aggregation == "sum":
        return float(sum(values))
    if aggregation == "max":
        return float(max(values))
    if aggregation == "min":
        return float(min(values))
    if aggregation == "count":
        return float(len(values))
    if aggregation == "rate":
        return float(statistics.mean(values))
    if aggregation == "p95":
        if len(values) >= 2:
            return float(statistics.quantiles(values, n=20)[-1])
        return float(values[0])
    return float(statistics.mean(values))


_PRIMITIVE_KINDS = {
    "turn_count",
    "main_stream_latency_p95",
    "main_stream_estimated_cost_usd",
    "tool_error_count",
    "guardrail_triggered",
    "opening_intent_class",
    "session_outcome",
    "interruption_count",
    "transfer_completed",
}


def _to_float(raw: Any) -> float | None:
    if isinstance(raw, bool):
        return 1.0 if raw else 0.0
    if isinstance(raw, (int, float)):
        return float(raw)
    return None


def _payment_success_binary(fv: dict[str, Any]) -> float:
    outcome = str(fv.get("session_outcome") or "").lower()
    return 1.0 if outcome in ("completed", "payment_success", "success") else 0.0


def _transfer_binary(fv: dict[str, Any]) -> float:
    if fv.get("transfer_completed"):
        return 1.0
    if str(fv.get("session_outcome") or "").lower() == "transferred":
        return 1.0
    return 0.0


def _component_session_value(comp: dict[str, Any], fv: dict[str, Any]) -> float | None:
    agg = (comp.get("aggregation") or "mean").lower()
    ref = comp.get("ref") or {}
    if agg == "count_transfer":
        return _transfer_binary(fv)
    if agg == "count_interruption":
        return float(fv.get("interruption_count") or 0)
    if agg == "rate_payment_success":
        return _payment_success_binary(fv)
    if agg == "rate" and (ref.get("kind") == "guardrail_triggered" or ref.get("name") == "all" and "guardrail" in str(ref)):
        return 1.0 if fv.get("guardrail_triggered") else 0.0
    if agg == "rate" and ref.get("kind") == "session_outcome":
        return resolve_component_value(ref, fv)
    return resolve_component_value(ref, fv)


def resolve_component_value(ref: dict[str, Any], fv: dict[str, Any]) -> float | None:
    """Map plan component ref {kind, name} to a numeric feature/signal value."""
    kind = (ref.get("kind") or "").strip()
    name = (ref.get("name") or "").strip()

    raw: Any = None
    if kind == "primitive" and name:
        raw = fv.get(name)
    elif kind == "session_outcome":
        outcome = str(fv.get("session_outcome") or "").lower()
        if name in ("payment_success", "completed", "success"):
            raw = 1.0 if outcome in ("completed", "payment_success", "success") else 0.0
        elif name in ("transferred_to_human", "transferred", "transfer", "transfer_to_human"):
            raw = 1.0 if fv.get("transfer_completed") or outcome == "transferred" else 0.0
        elif name:
            raw = 1.0 if name.lower() in outcome else 0.0
        else:
            raw = outcome
    elif kind == "turn_count" and name in ("interruption", "interruption_count"):
        raw = fv.get("interruption_count")
    elif kind == "tool_error_count" or (kind == "tool_error_count" and name in ("all", "")):
        raw = fv.get("tool_error_count")
    elif kind == "main_stream_latency_p95" or (kind == "main_stream_latency_p95" and name in ("all", "")):
        raw = fv.get("main_stream_latency_p95")
    elif kind in _PRIMITIVE_KINDS and kind in fv:
        raw = fv[kind]
    elif name in fv:
        raw = fv[name]
    elif kind in fv:
        raw = fv[kind]
    else:
        return None

    return _to_float(raw)


def aspect_value(aspect: dict, fv: dict[str, Any]) -> float | None:
    components = aspect.get("components") or []
    if not components:
        name = aspect.get("id") or aspect.get("name")
        return _to_float(fv.get(name))
    vals = []
    for comp in components:
        raw = _component_session_value(comp, fv)
        if raw is not None:
            vals.append(raw)
    if not vals:
        return None
    return _aggregate(vals, (components[0].get("aggregation") or "mean").lower())


def _cohort_medians(cohort_ids: dict[str, list[str]], store) -> dict[str, float]:
    turn_counts: list[float] = []
    for ids in cohort_ids.values():
        for sid in ids:
            p = store.features_dir / f"{sid}.json"
            if not p.exists():
                continue
            fv = store.read_json(p)
            tc = fv.get("turn_count")
            if isinstance(tc, (int, float)):
                turn_counts.append(float(tc))
    medians: dict[str, float] = {}
    if turn_counts:
        med = float(statistics.median(turn_counts))
        medians["median(turn_count)"] = med
        medians["median_turn_count"] = med
    return medians


def enrich_evaluation_values(
    fv: dict[str, Any],
    aspect_vals: dict[str, float],
    cohort_medians: dict[str, float],
) -> dict[str, Any]:
    values = dict(fv)
    values.update(aspect_vals)
    values["transfer_count"] = _transfer_binary(fv)
    ps = _payment_success_binary(fv)
    values["payment_success"] = ps
    values["payment_success_rate"] = ps
    values["llm_error_count"] = float(fv.get("tool_error_count") or aspect_vals.get("llm_error_count") or 0)
    values["interruption_count"] = float(fv.get("interruption_count") or 0)
    values["guardrail_triggered"] = 1.0 if fv.get("guardrail_triggered") else 0.0
    values.update(cohort_medians)
    return values


def _significance_test(before: list[float], after: list[float], significance_level: float) -> dict[str, Any]:
    if len(before) < 2 or len(after) < 2:
        return {"p_value": 1.0, "significant": False, "test": "insufficient_data"}
    try:
        _, p = stats.mannwhitneyu(before, after, alternative="two-sided")
        return {"p_value": round(float(p), 4), "significant": float(p) < significance_level, "test": "mann_whitney"}
    except Exception:
        return {"p_value": 1.0, "significant": False, "test": "error"}


def _rate_test(before_matches: int, before_n: int, after_matches: int, after_n: int, significance_level: float) -> dict[str, Any]:
    table = [[before_matches, before_n - before_matches], [after_matches, after_n - after_matches]]
    try:
        if before_n < 5 or after_n < 5:
            _, p = stats.fisher_exact(table)
            test = "fisher"
        else:
            _, p, _, _ = stats.chi2_contingency(table)
            test = "chi_square"
        return {"p_value": round(float(p), 4), "significant": float(p) < significance_level, "test": test}
    except Exception:
        return {"p_value": 1.0, "significant": False, "test": "error"}


def pick_counter_examples(
    per_conversation: dict[str, dict],
    hypothesis_id: str,
    cohort_ids: dict[str, list[str]],
    k: int = 3,
) -> list[str]:
    candidates = []
    for label, ids in cohort_ids.items():
        for sid in ids:
            row = per_conversation.get(sid)
            if not row:
                continue
            if row.get("hypotheses", {}).get(hypothesis_id):
                continue
            candidates.append((sid, row))
    if not candidates:
        return []
    random.shuffle(candidates)
    selected = [candidates[0][0]]
    seed_vec = candidates[0][1].get("values", {}).get("embedding_opening")
    vecs = [seed_vec] if seed_vec else []
    while len(selected) < min(k, len(candidates)):
        best_sid, best_d = None, -1.0
        for sid, row in candidates:
            if sid in selected:
                continue
            emb = row.get("values", {}).get("embedding_opening")
            if not emb or not vecs:
                best_sid = sid
                break
            d = min(cosine_distance(emb, v) for v in vecs if v)
            if d > best_d:
                best_d, best_sid = d, sid
        if best_sid is None:
            break
        selected.append(best_sid)
        emb = per_conversation[best_sid]["values"].get("embedding_opening")
        if emb:
            vecs.append(emb)
    return selected


def run_evaluation(
    plan: dict[str, Any],
    cohort_ids: dict[str, list[str]],
    store,
    req: dict[str, Any],
    load_conversation,
) -> dict[str, Any]:
    min_support = int(req.get("min_support") or 30)
    significance_level = float(req.get("significance_level") or 0.05)
    is_comparative = req.get("study_type") == "comparative"
    aspects = ((plan.get("quantitative") or {}).get("aspects") or [])
    hypotheses = ((plan.get("qualitative") or {}).get("hypotheses") or [])

    total_n = sum(len(v) for v in cohort_ids.values())
    executor = SignalExecutor(plan, eval_session_count=total_n)
    cohort_medians = _cohort_medians(cohort_ids, store)
    jobs: list[tuple[str, str]] = []
    for cohort_label, ids in cohort_ids.items():
        for sid in ids:
            jobs.append((cohort_label, sid))

    def _eval_one(job: tuple[str, str]) -> dict[str, Any]:
        cohort_label, sid = job
        fv_path = store.features_dir / f"{sid}.json"
        fv = store.read_json(fv_path) if fv_path.exists() else {}
        conv = load_conversation(store, sid)
        executor.compute_values(fv, conv)
        aspect_vals: dict[str, float] = {}
        for aspect in aspects:
            av = aspect_value(aspect, fv)
            if av is not None:
                aid = aspect.get("id") or aspect.get("name")
                aspect_vals[aid] = av
        values = enrich_evaluation_values(fv, aspect_vals, cohort_medians)
        hyp_matches = {
            h.get("id"): eval_hypothesis(normalize_hypothesis_predicate(h.get("predicate"), h), values)
            for h in hypotheses
        }
        row = {
            "session_id": sid,
            "cohort": cohort_label,
            "values": values,
            "hypotheses": hyp_matches,
        }
        row["_aspect_vals"] = aspect_vals
        return row

    rows = run_parallel(jobs, _eval_one, max_workers=worker_count(), label="phase3-eval")
    per_conversation: dict[str, dict] = {}
    per_cohort_aspect: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        if not row:
            continue
        sid = row["session_id"]
        per_conversation[sid] = {k: v for k, v in row.items() if not k.startswith("_")}
        cohort_label = row["cohort"]
        for key, av in (row.get("_aspect_vals") or {}).items():
            per_cohort_aspect[cohort_label][key].append(av)

    aspect_results = []
    for aspect in aspects:
        name = aspect.get("id") or aspect.get("name")
        if is_comparative:
            b_vals = per_cohort_aspect.get("before", {}).get(name) or []
            a_vals = per_cohort_aspect.get("after", {}).get(name) or []
            b = statistics.mean(b_vals) if b_vals else 0
            a = statistics.mean(a_vals) if a_vals else 0
            delta_pct = 0 if b == 0 else (a - b) / b * 100
            sig = _significance_test(b_vals, a_vals, significance_level)
            aspect_results.append({
                "id": name,
                "name": aspect.get("name") or name,
                "before": round(b, 3),
                "after": round(a, 3),
                "delta_pct": round(delta_pct, 1),
                "good_if": "down" if any(x in name for x in ("latency", "cost", "error")) else "up",
                "proof": {"significance_level": significance_level, **sig},
            })
        else:
            vals = per_cohort_aspect.get("all", {}).get(name) or []
            if not vals:
                # No session resolved a value for this aspect (usually a
                # component ref/kind the resolver doesn't recognize) --
                # that's missing data, not a measured zero. Don't fabricate one.
                aspect_results.append({
                    "id": name, "name": aspect.get("name") or name,
                    "value": None, "before": None, "after": None,
                    "delta_pct": None, "good_if": "down", "no_data": True,
                })
                continue
            m = statistics.mean(vals)
            aspect_results.append({
                "id": name,
                "name": aspect.get("name") or name,
                "value": round(m, 3),
                # Single-cohort has no real before/after split -- leave these
                # null instead of duplicating `value` into both, which used
                # to render as a fake "0% change" comparison.
                "before": None,
                "after": None,
                "delta_pct": None,
                "good_if": "down",
            })

    hypothesis_results = []
    for hyp in hypotheses:
        hid = hyp.get("id")
        rates = {}
        for cohort_label, ids in cohort_ids.items():
            matches = sum(1 for sid in ids if per_conversation.get(sid, {}).get("hypotheses", {}).get(hid))
            rates[cohort_label] = {"support": matches, "rate": matches / len(ids) if ids else 0}
        total_support = sum(r["support"] for r in rates.values())
        proof = {}
        if is_comparative:
            b = rates.get("before") or {"support": 0}
            a = rates.get("after") or {"support": 0}
            proof = _rate_test(
                b["support"], len(cohort_ids.get("before") or []),
                a["support"], len(cohort_ids.get("after") or []),
                significance_level,
            )
        counter_examples = pick_counter_examples(per_conversation, hid, cohort_ids)
        notes = []
        for sid in counter_examples[:3]:
            fv = per_conversation[sid]["values"]
            conv = load_conversation(store, sid)
            note_val = executor.compute_values(fv, conv, hypothesis_id=hid, counter_example_mode=True)
            notes.append({"session_id": sid, "note": str(note_val.get(hid) or "")[:500]})
        hypothesis_results.append({
            "id": hid,
            "title": hyp.get("title"),
            "description": hyp.get("description"),
            "rates": rates,
            "rejected": total_support < min_support,
            "counter_examples": counter_examples,
            "counter_example_notes": notes,
            "proof": {"min_support": min_support, "significance_level": significance_level, **proof},
        })

    return {
        "per_conversation": per_conversation,
        "aspects": aspect_results,
        "hypotheses": hypothesis_results,
    }
