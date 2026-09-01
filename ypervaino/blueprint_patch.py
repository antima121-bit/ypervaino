from __future__ import annotations

import copy
from typing import Any


class PatchError(Exception):
    def __init__(self, code: str, message: str, op_index: int = 0):
        super().__init__(message)
        self.code = code
        self.op_index = op_index
        self.message = message


def _assistant_info(bp: dict[str, Any]) -> dict[str, Any]:
    return bp.setdefault("assistant_info", {})


def _find_skill(bp: dict[str, Any], skill_name: str | None, skill_id: str | None) -> dict[str, Any] | None:
    skills = _assistant_info(bp).get("skill_list") or []
    for sk in skills:
        if skill_id and sk.get("id") == skill_id:
            return sk
        if skill_name and (sk.get("name") or "").lower() == skill_name.lower():
            return sk
    return None


def _find_tool(skill: dict[str, Any], tool_name: str | None, tool_id: str | None) -> dict[str, Any] | None:
    for tool in skill.get("tools") or []:
        if tool_id and tool.get("id") == tool_id:
            return tool
        if tool_name and (tool.get("name") or "").lower() == tool_name.lower():
            return tool
    return None


def _resolve_text_container(bp: dict[str, Any], target: dict[str, Any]) -> tuple[Any, str]:
    domain = target.get("domain") or ""
    field = target.get("field_path") or "instructions"
    if domain == "skill.instructions":
        sk = _find_skill(bp, target.get("skill_name"), target.get("skill_id"))
        if not sk:
            raise PatchError("TARGET_NOT_FOUND", f"Skill not found: {target.get('skill_name')}")
        return sk, field if field in sk else "instructions"
    if domain == "welcome_message":
        info = _assistant_info(bp)
        return info, "welcome_message"
    if domain == "global_guidelines":
        info = _assistant_info(bp)
        return info, "guidelines_and_rules"
    if domain in ("skill.description",):
        sk = _find_skill(bp, target.get("skill_name"), target.get("skill_id"))
        if not sk:
            raise PatchError("TARGET_NOT_FOUND", f"Skill not found: {target.get('skill_name')}")
        return sk, "description"
    if domain in ("tool.schema", "tool.description"):
        sk = _find_skill(bp, target.get("skill_name"), target.get("skill_id"))
        if not sk:
            raise PatchError("TARGET_NOT_FOUND", f"Skill not found: {target.get('skill_name')}")
        tool = _find_tool(sk, target.get("tool_name"), target.get("tool_id"))
        if not tool:
            raise PatchError("TARGET_NOT_FOUND", f"Tool not found: {target.get('tool_name')}")
        key = "description" if domain == "tool.description" else (target.get("field_path") or "description")
        return tool, key
    if domain == "dialog_flow.node_instructions" and target.get("node_id"):
        return bp, f"_node_instructions:{target['node_id']}"
    raise PatchError("TARGET_NOT_FOUND", f"Unsupported target domain: {domain}")


def _get_text(bp: dict[str, Any], dialog_flow: dict[str, Any] | None, target: dict[str, Any]) -> str:
    if target.get("field_path", "").startswith("_node_instructions:"):
        node_id = target["field_path"].split(":", 1)[1]
        return _get_node_field(dialog_flow, node_id, "instructions") or ""
    container, key = _resolve_text_container(bp, target)
    val = container.get(key)
    return val if isinstance(val, str) else ""


def _set_text(bp: dict[str, Any], dialog_flow: dict[str, Any] | None, target: dict[str, Any], text: str) -> None:
    if target.get("field_path", "").startswith("_node_instructions:"):
        node_id = target["field_path"].split(":", 1)[1]
        _set_node_field(dialog_flow, node_id, "instructions", text)
        return
    container, key = _resolve_text_container(bp, target)
    container[key] = text


def _get_node_field(dialog_flow: dict[str, Any] | None, node_id: str, prop: str) -> Any:
    if not dialog_flow:
        return None
    for node in dialog_flow.get("nodes") or []:
        if node.get("id") == node_id:
            return node.get(prop)
    return None


def _set_node_field(dialog_flow: dict[str, Any] | None, node_id: str, prop: str, value: Any) -> None:
    if dialog_flow is None:
        raise PatchError("TARGET_NOT_FOUND", "Dialog flow not loaded")
    for node in dialog_flow.get("nodes") or []:
        if node.get("id") == node_id:
            node[prop] = value
            return
    raise PatchError("TARGET_NOT_FOUND", f"Node not found: {node_id}")


def _match_replace(text: str, find: str, replace: str, match: str = "exact") -> str:
    if match == "all":
        return text.replace(find, replace)
    if match == "first":
        idx = text.find(find)
        if idx < 0:
            raise PatchError("ANCHOR_NOT_FOUND", f"Text not found: {find[:80]}")
        return text[:idx] + replace + text[idx + len(find):]
    if text.count(find) != 1:
        count = text.count(find)
        raise PatchError("ANCHOR_NOT_FOUND", f"Expected exactly one match, found {count}")
    return text.replace(find, replace, 1)


def _require_op_fields(op: dict[str, Any], fields: list[str], op_index: int) -> None:
    missing = [f for f in fields if f not in op or op[f] is None]
    if missing:
        raise PatchError("INVALID_OP", f"Missing fields {missing} for op {op.get('op')}", op_index)


def apply_op(
    bp: dict[str, Any],
    dialog_flow: dict[str, Any] | None,
    op: dict[str, Any],
    target: dict[str, Any],
    op_index: int = 0,
) -> None:
    kind = op.get("op")
    if kind == "replace_text":
        _require_op_fields(op, ["find", "replace"], op_index)
        text = _get_text(bp, dialog_flow, target)
        new_text = _match_replace(text, op["find"], op["replace"], op.get("match", "exact"))
        _set_text(bp, dialog_flow, target, new_text)
        return
    if kind == "insert_after":
        _require_op_fields(op, ["anchor", "text"], op_index)
        text = _get_text(bp, dialog_flow, target)
        anchor = op["anchor"]
        idx = text.find(anchor)
        if idx < 0:
            raise PatchError("ANCHOR_NOT_FOUND", f"Anchor not found: {anchor[:80]}", op_index)
        insert_at = idx + len(anchor)
        new_text = text[:insert_at] + op["text"] + text[insert_at:]
        _set_text(bp, dialog_flow, target, new_text)
        return
    if kind == "insert_before":
        _require_op_fields(op, ["anchor", "text"], op_index)
        text = _get_text(bp, dialog_flow, target)
        anchor = op["anchor"]
        idx = text.find(anchor)
        if idx < 0:
            raise PatchError("ANCHOR_NOT_FOUND", f"Anchor not found: {anchor[:80]}", op_index)
        new_text = text[:idx] + op["text"] + text[idx:]
        _set_text(bp, dialog_flow, target, new_text)
        return
    if kind == "delete_text":
        _require_op_fields(op, ["find"], op_index)
        text = _get_text(bp, dialog_flow, target)
        find = op["find"]
        match = op.get("match", "exact")
        if match == "all":
            new_text = text.replace(find, "")
        elif match == "first":
            idx = text.find(find)
            if idx < 0:
                raise PatchError("ANCHOR_NOT_FOUND", f"Text not found: {find[:80]}", op_index)
            new_text = text[:idx] + text[idx + len(find):]
        else:
            if text.count(find) != 1:
                raise PatchError("ANCHOR_NOT_FOUND", f"Expected one match for delete, found {text.count(find)}", op_index)
            new_text = text.replace(find, "", 1)
        _set_text(bp, dialog_flow, target, new_text)
        return
    if kind in ("replace_field", "append", "prepend"):
        container, key = _resolve_text_container(bp, target)
        val = op.get("value")
        if kind == "replace_field":
            container[key] = val
        elif kind == "append":
            existing = container.get(key)
            if isinstance(existing, str):
                container[key] = existing + str(val)
            elif isinstance(existing, list):
                existing.append(val)
            else:
                container[key] = val
        else:
            existing = container.get(key)
            if isinstance(existing, str):
                container[key] = str(val) + existing
            elif isinstance(existing, list):
                existing.insert(0, val)
            else:
                container[key] = val
        return
    if kind == "set_node_property":
        _set_node_field(dialog_flow, op["node_id"], op["property"], op["value"])
        return
    if kind == "replace_node_instructions":
        _set_node_field(dialog_flow, op["node_id"], "instructions", op["value"])
        return
    if kind == "add_edge":
        if dialog_flow is None:
            raise PatchError("TARGET_NOT_FOUND", "Dialog flow not loaded", op_index)
        edges = dialog_flow.setdefault("edges", [])
        edges.append({
            "id": op.get("edge_id"),
            "from": op["from_node_id"],
            "to": op["to_node_id"],
            "condition": op.get("condition"),
        })
        return
    if kind == "remove_edge":
        if dialog_flow is None:
            raise PatchError("TARGET_NOT_FOUND", "Dialog flow not loaded", op_index)
        edges = dialog_flow.get("edges") or []
        dialog_flow["edges"] = [e for e in edges if e.get("id") != op["edge_id"]]
        return
    if kind == "update_edge":
        if dialog_flow is None:
            raise PatchError("TARGET_NOT_FOUND", "Dialog flow not loaded", op_index)
        for edge in dialog_flow.get("edges") or []:
            if edge.get("id") == op["edge_id"]:
                edge[op["property"]] = op["value"]
                return
        raise PatchError("TARGET_NOT_FOUND", f"Edge not found: {op['edge_id']}", op_index)
    raise PatchError("UNKNOWN_OP", f"Unknown op: {kind}", op_index)


def apply_patch(
    blueprint: dict[str, Any],
    patch: dict[str, Any],
    target: dict[str, Any],
    dialog_flow: dict[str, Any] | None = None,
    dry_run: bool = False,
) -> tuple[dict[str, Any], dict[str, Any] | None, list[dict[str, Any]]]:
    bp = copy.deepcopy(blueprint)
    df = copy.deepcopy(dialog_flow) if dialog_flow else None
    errors: list[dict[str, Any]] = []
    applied = 0
    for i, op in enumerate(patch.get("ops") or []):
        if not isinstance(op, dict):
            errors.append({"op_index": i, "code": "INVALID_OP", "message": "Op is not an object"})
            continue
        try:
            apply_op(bp, df, op, target, i)
            applied += 1
        except PatchError as e:
            errors.append({"op_index": i, "code": e.code, "message": e.message})
            if not dry_run:
                raise
        except (KeyError, TypeError) as e:
            errors.append({"op_index": i, "code": "INVALID_OP", "message": str(e)})
            if not dry_run:
                raise PatchError("INVALID_OP", str(e), i) from e
    if dry_run and errors:
        return bp, df, errors
    return bp, df, errors if dry_run else []
