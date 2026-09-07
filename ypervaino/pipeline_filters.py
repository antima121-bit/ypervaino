from __future__ import annotations

from typing import Any


def _resolve_target(atom: dict[str, Any]) -> tuple[Any, bool]:
    if atom.get("value") is not None:
        target = atom["value"]
    else:
        target = atom.get("user_value")
    if atom.get("value_transform") == "minutes_to_ms" and target is not None:
        try:
            target = float(target) * 60_000
        except (TypeError, ValueError):
            return target, False
    return target, True


def _atom_matches(val: Any, target: Any, op: str) -> bool:
    if op == "==":
        return val == target
    if op == "!=":
        return val != target
    if op == ">=":
        return val is not None and val >= target
    if op == "<=":
        return val is not None and val <= target
    if op == ">":
        return val is not None and val > target
    if op == "in":
        return val in (target or [])
    if op == "contains":
        return isinstance(val, (list, tuple, set)) and target in val
    return False


def filter_failure_reasons(features: dict[str, Any], compiled: list[dict]) -> list[str]:
    reasons: list[str] = []
    for atom in compiled:
        prim = atom["primitive"]
        op = atom["op"]
        val = features.get(prim)
        target, valid = _resolve_target(atom)
        if not valid:
            label = atom.get("label") or atom.get("id") or prim
            reasons.append(f"{label}: invalid filter value {target!r}")
            continue
        if not _atom_matches(val, target, op):
            label = atom.get("label") or atom.get("id") or prim
            reasons.append(f"{label}: {prim} {op} {target!r}, got {val!r}")
    return reasons


def passes_filters(features: dict[str, Any], compiled: list[dict]) -> bool:
    return not filter_failure_reasons(features, compiled)
