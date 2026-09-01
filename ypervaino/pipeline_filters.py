from __future__ import annotations

from typing import Any


def passes_filters(features: dict[str, Any], compiled: list[dict]) -> bool:
    for atom in compiled:
        prim = atom["primitive"]
        op = atom["op"]
        if prim == "agent_ever":
            name = (atom.get("user_value") or "").lower()
            if name and name not in (features.get("agent_path") or "").lower():
                return False
            continue
        val = features.get(prim)
        if atom.get("value") is not None:
            target = atom["value"]
        else:
            target = atom.get("user_value")
        if atom.get("value_transform") == "minutes_to_ms" and target is not None:
            try:
                target = float(target) * 60_000
            except (TypeError, ValueError):
                return False
        if op == "==":
            if val != target:
                return False
        elif op == "!=":
            if val == target:
                return False
        elif op == ">=":
            if val is None or val < target:
                return False
        elif op == "<=":
            if val is None or val > target:
                return False
        elif op == ">":
            if val is None or val <= target:
                return False
        elif op == "in":
            if val not in (target or []):
                return False
    return True
