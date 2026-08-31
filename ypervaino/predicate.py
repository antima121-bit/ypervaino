from __future__ import annotations

import re
from typing import Any


def _parse_literal(s: str) -> Any:
    s = s.strip().strip("'\"")
    if s.lower() in ("true", "false"):
        return s.lower() == "true"
    try:
        return float(s) if "." in s else int(s)
    except ValueError:
        return s


def parse_predicate(node: Any) -> Any:
    if isinstance(node, str):
        return _parse_predicate_string(node)
    return node


def _parse_predicate_string(s: str) -> dict[str, Any]:
    s = s.strip()
    if not s:
        return {"op": "CMP", "name": "_", "cmp": "==", "value": True}
    and_parts = re.split(r"\s+and\s+", s, flags=re.I)
    if len(and_parts) > 1:
        return {"op": "AND", "args": [_parse_predicate_string(p.strip()) for p in and_parts]}
    or_parts = re.split(r"\s+or\s+", s, flags=re.I)
    if len(or_parts) > 1:
        return {"op": "OR", "args": [_parse_predicate_string(p.strip()) for p in or_parts]}
    m = re.match(r"^([\w_]+)\s*(>=|<=|!=|>|<|==|=)\s*(.+)$", s)
    if m:
        name, cmp_op, val = m.groups()
        if cmp_op == "=":
            cmp_op = "=="
        return {"op": "CMP", "name": name, "cmp": cmp_op, "value": _parse_literal(val)}
    return {"op": "CMP", "name": s, "cmp": "==", "value": True}


def eval_predicate(node: Any, values: dict[str, Any]) -> bool:
    node = parse_predicate(node)
    if node is None:
        return True
    if isinstance(node, bool):
        return node
    if not isinstance(node, dict):
        return False

    op = (node.get("op") or "").upper()
    if op == "AND":
        children = node.get("args") or node.get("nodes") or []
        return all(eval_predicate(c, values) for c in children)
    if op == "OR":
        children = node.get("args") or node.get("nodes") or []
        return any(eval_predicate(c, values) for c in children)
    if op == "NOT":
        child = (node.get("args") or node.get("nodes") or [None])[0]
        return not eval_predicate(child, values)
    if op in ("CMP", "COMPARISON") or node.get("cmp") or node.get("operator"):
        return _eval_cmp(node, values)
    if op == "IS_NULL":
        return values.get(node.get("name")) is None
    if op == "IN":
        return values.get(node.get("name")) in (node.get("value") or [])
    if op == "BETWEEN":
        val = values.get(node.get("name"))
        lo, hi = node.get("value") or [None, None]
        return val is not None and lo is not None and hi is not None and lo <= val <= hi
    return False


def _coerce_pair(val: Any, target: Any) -> tuple[Any, Any]:
    if isinstance(val, bool) or isinstance(target, bool):
        return (1 if val else 0, 1 if target else 0)
    if isinstance(val, (int, float)) and isinstance(target, str):
        try:
            target = float(target) if "." in str(target) else int(target)
        except (TypeError, ValueError):
            pass
    if isinstance(val, str) and isinstance(target, str):
        return val, target
    return val, target


def _resolve_cmp_target(target: Any, values: dict[str, Any]) -> Any:
    if isinstance(target, str) and target.startswith("median(") and target.endswith(")"):
        if target in values:
            return values[target]
        field = target[7:-1].strip()
        return values.get(f"median_{field}") or values.get(f"median({field})")
    return target


def _eval_cmp(node: dict, values: dict[str, Any]) -> bool:
    name = node.get("name")
    val = values.get(name)
    cmp = node.get("cmp") or node.get("operator") or "=="
    target = _resolve_cmp_target(node.get("value"), values)
    if cmp in ("=", "=="):
        if isinstance(val, (int, float)) and isinstance(target, (int, float)):
            return float(val) == float(target)
        return val == target
    if cmp == "!=":
        return val != target
    try:
        val, target = _coerce_pair(val, target)
        if isinstance(val, str) or isinstance(target, str):
            return False
        if not isinstance(val, (int, float)) or not isinstance(target, (int, float)):
            return False
        if cmp == ">":
            return val > target
        if cmp == ">=":
            return val >= target
        if cmp == "<":
            return val < target
        if cmp == "<=":
            return val <= target
    except TypeError:
        return False
    return False
