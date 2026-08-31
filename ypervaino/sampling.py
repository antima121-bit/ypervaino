from __future__ import annotations

import math
import random
from collections import defaultdict
from typing import Any

from ypervaino.features import stratum_key


def _allocate_quotas(strata: dict[Any, list[str]], total: int) -> dict[Any, int]:
    if total <= 0 or not strata:
        return {}
    sizes = {k: len(v) for k, v in strata.items()}
    grand = sum(sizes.values())
    if grand == 0:
        return {}
    raw = {k: total * sizes[k] / grand for k in sizes}
    quotas = {k: int(math.floor(v)) for k, v in raw.items()}
    rem = total - sum(quotas.values())
    order = sorted(raw.keys(), key=lambda k: (raw[k] - quotas[k]), reverse=True)
    for k in order:
        if rem <= 0:
            break
        if quotas[k] < sizes[k]:
            quotas[k] += 1
            rem -= 1
    return quotas


def stratified_subsample(
    items: list[tuple[str, dict[str, Any]]],
    n: int,
    *,
    prioritize_rare: bool = True,
) -> list[str]:
    """Stratified subsample by (intent, outcome, length)."""
    if n >= len(items):
        return [sid for sid, _ in items]
    strata: dict[tuple[str, str, str], list[tuple[str, dict]]] = defaultdict(list)
    for sid, fv in items:
        strata[stratum_key(fv)].append((sid, fv))
    quotas = _allocate_quotas({k: [x[0] for x in v] for k, v in strata.items()}, n)
    if prioritize_rare:
        quotas = dict(sorted(quotas.items(), key=lambda kv: len(strata[kv[0]])))
    picked: list[str] = []
    for sk, quota in quotas.items():
        pool = [sid for sid, _ in strata[sk]]
        random.shuffle(pool)
        picked.extend(pool[:quota])
    if len(picked) < n:
        rest = [sid for sid, _ in items if sid not in picked]
        random.shuffle(rest)
        picked.extend(rest[: n - len(picked)])
    return picked[:n]
