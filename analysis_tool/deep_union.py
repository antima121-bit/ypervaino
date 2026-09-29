"""Deep union of ordered_events across parsed session traces."""

from __future__ import annotations

import copy
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PRIMITIVE_CAP_DEFAULT = 10
PRIMITIVE_CAP_USER_RESPONSE_CONTENT = 100
TRANSCRIPT_CONTENT_EVENT_TYPES = frozenset({"USER_QUERY", "RESPONSE.FINAL"})
OUTPUT_FILENAME = "deep_union_over_parsed_traces.json"


def _primitive_cap_for_path(path: tuple[str, ...]) -> int:
    if len(path) >= 2 and path[-1] == "content" and path[0] in TRANSCRIPT_CONTENT_EVENT_TYPES:
        return PRIMITIVE_CAP_USER_RESPONSE_CONTENT
    return PRIMITIVE_CAP_DEFAULT


class UnionTypeConflictError(TypeError):
    """Incompatible JSON shapes at the same field path during deep union."""

    def __init__(
        self,
        path: tuple[str, ...],
        existing: str,
        new: str,
        *,
        session_source: str | None = None,
        value_preview: str | None = None,
    ) -> None:
        self.path = path
        self.field_path = ".".join(path) if path else "<root>"
        self.existing = existing
        self.new = new
        self.session_source = session_source
        self.value_preview = value_preview
        parts = [
            f"Deep union type conflict at field `{self.field_path}`",
            f"expected {existing}, saw {new}",
        ]
        if session_source:
            parts.append(f"while merging parsed trace `{session_source}`")
        if value_preview:
            parts.append(f"offending value preview: {value_preview}")
        super().__init__(" — ".join(parts))


def _value_preview(value: Any, max_len: int = 120) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, default=repr)
    except (TypeError, ValueError):
        text = repr(value)
    if len(text) > max_len:
        return text[: max_len - 3] + "..."
    return text


def _coerce_numeric(value: Any) -> Any:
    if type(value) is int:
        return float(value)
    return value


def _primitive_kind(value: Any, path: tuple[str, ...]) -> str:
    if value is None:
        return "null"
    if type(value) is bool:
        return "bool"
    if type(value) is int or type(value) is float:
        return "float"
    if type(value) is str:
        return "str"
    raise UnionTypeConflictError(
        path,
        "primitive (null, bool, int, float, or str)",
        type(value).__name__,
        value_preview=_value_preview(value),
    )


def _merge_primitive(leaf: dict[str, Any], value: Any, path: tuple[str, ...]) -> None:
    if value is None:
        return
    value = _coerce_numeric(value)
    kind = _primitive_kind(value, path)
    if "kind" not in leaf:
        leaf["kind"] = kind
    elif leaf["kind"] != kind:
        raise UnionTypeConflictError(path, leaf["kind"], kind)

    values: list[Any] = leaf.setdefault("values", [])
    if len(values) >= _primitive_cap_for_path(path):
        return
    if value in values:
        return
    values.append(value)


def _merge_list_of_dicts(acc: dict[str, Any], items: list[Any], path: tuple[str, ...]) -> None:
    if not items:
        return
    if "kind" in acc:
        raise UnionTypeConflictError(path, f"leaf({acc['kind']})", "list of dict")

    for item in items:
        if isinstance(item, dict):
            if not item:
                continue
            _merge_node(acc, item, path)
            continue
        if isinstance(item, list):
            raise UnionTypeConflictError(
                path,
                "list of dict",
                "list (nested list)",
                value_preview=_value_preview(item),
            )
        raise UnionTypeConflictError(
            path,
            "list of dict",
            f"primitive ({_primitive_kind(item, path)})",
            value_preview=_value_preview(item),
        )


def _merge_list_at_key(acc: dict[str, Any], key: str, items: list[Any], path: tuple[str, ...]) -> None:
    if not items:
        return
    branch = acc.setdefault(key, {})
    if "kind" in branch:
        raise UnionTypeConflictError(
            path,
            f"leaf({branch['kind']})",
            "list of dict",
            value_preview=_value_preview(items),
        )
    _merge_list_of_dicts(branch, items, path)


def _merge_node(acc: dict[str, Any], value: Any, path: tuple[str, ...]) -> None:
    if isinstance(value, dict):
        if not value:
            return
        for key, child in value.items():
            if not isinstance(key, str):
                raise UnionTypeConflictError(path, "dict key", type(key).__name__)
            child_path = path + (key,)
            if isinstance(child, dict):
                if not child:
                    continue
                branch = acc.setdefault(key, {})
                if "kind" in branch:
                    raise UnionTypeConflictError(child_path, f"leaf({branch['kind']})", "dict")
                _merge_node(branch, child, child_path)
            elif isinstance(child, list):
                _merge_list_at_key(acc, key, child, child_path)
            else:
                existing = acc.get(key)
                if isinstance(existing, dict) and "kind" not in existing and existing:
                    raise UnionTypeConflictError(
                        child_path,
                        "dict (nested object)",
                        _primitive_kind(child, child_path),
                    )
                leaf = acc.setdefault(key, {})
                _merge_primitive(leaf, child, child_path)
        return

    if isinstance(value, list):
        _merge_list_of_dicts(acc, value, path)
        return

    _merge_primitive(acc.setdefault("__leaf__", {}), value, path)


def _ordered_event_type(entry: dict[str, Any]) -> str:
    if len(entry) == 1:
        key = next(iter(entry.keys()))
        if isinstance(key, str):
            return key
    return "unknown"


def _merge_ordered_event(acc: dict[str, Any], event_entry: dict[str, Any]) -> None:
    if len(event_entry) != 1:
        raise ValueError(f"ordered_events entry must have exactly one event type key, got {list(event_entry)}")
    event_type, payload = next(iter(event_entry.items()))
    if not isinstance(event_type, str):
        raise ValueError(f"Invalid event type key: {event_type!r}")
    branch = acc.setdefault(event_type, {})
    if "kind" in branch:
        raise UnionTypeConflictError((event_type,), f"leaf({branch['kind']})", "dict")
    _merge_node(branch, payload, (event_type,))


def _materialize(node: dict[str, Any]) -> dict[str, Any] | list[Any] | None:
    if "kind" in node:
        return list(node.get("values", []))
    out: dict[str, Any] = {}
    for key, child in node.items():
        if key == "__leaf__":
            materialized = _materialize(child)
            if materialized is not None and materialized != []:
                raise ValueError("Internal __leaf__ produced unexpected materialized value")
            continue
        if not isinstance(child, dict):
            raise ValueError(f"Expected dict branch at {key!r}")
        materialized = _materialize(child)
        if materialized is None:
            continue
        if isinstance(materialized, dict) and not materialized:
            continue
        out[key] = materialized
    return out if out else None


SKIPPED_EVENTS_META_CAP = 100


def _merge_sessions_into_acc(
    acc: dict[str, Any],
    ordered_events_list: list[list[dict[str, Any]]],
    *,
    session_sources: list[str] | None = None,
) -> tuple[int, int, list[dict[str, Any]]]:
    entries_merged = 0
    skipped_count = 0
    skipped: list[dict[str, Any]] = []
    for session_idx, ordered in enumerate(ordered_events_list):
        source = (
            session_sources[session_idx]
            if session_sources and session_idx < len(session_sources)
            else None
        )
        for entry in ordered:
            if not isinstance(entry, dict):
                continue
            trial = copy.deepcopy(acc)
            try:
                _merge_ordered_event(trial, entry)
            except UnionTypeConflictError as exc:
                session_name = source or exc.session_source or "unknown"
                logger.warning(
                    "Deep union skipping ordered event (schema mismatch): "
                    "event_type=%s field=%s expected=%s saw=%s session=%s%s",
                    _ordered_event_type(entry),
                    exc.field_path,
                    exc.existing,
                    exc.new,
                    session_name,
                    f" preview={exc.value_preview!r}" if exc.value_preview else "",
                )
                skipped_count += 1
                if len(skipped) < SKIPPED_EVENTS_META_CAP:
                    skipped.append(
                        {
                            "session": session_name,
                            "event_type": _ordered_event_type(entry),
                            "field_path": exc.field_path,
                            "expected": exc.existing,
                            "saw": exc.new,
                            "value_preview": exc.value_preview,
                        }
                    )
                continue
            acc.clear()
            acc.update(trial)
            entries_merged += 1
    return entries_merged, skipped_count, skipped


def _union_payload_meta(
    sessions_merged: int,
    entries_merged: int,
    skipped_count: int,
    skipped: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "sessions_merged": sessions_merged,
        "ordered_event_entries_merged": entries_merged,
        "ordered_event_entries_skipped_schema_mismatch": skipped_count,
        "skipped_ordered_events": skipped,
        "primitive_value_caps": {
            "default": PRIMITIVE_CAP_DEFAULT,
            "USER_QUERY.content": PRIMITIVE_CAP_USER_RESPONSE_CONTENT,
            "RESPONSE.FINAL.content": PRIMITIVE_CAP_USER_RESPONSE_CONTENT,
        },
    }


def deep_union_ordered_events(ordered_events_list: list[list[dict[str, Any]]]) -> dict[str, Any]:
    acc: dict[str, Any] = {}
    entries_merged, skipped_count, skipped = _merge_sessions_into_acc(acc, ordered_events_list)

    materialized = _materialize(acc)
    result = materialized if isinstance(materialized, dict) else {}
    return {
        "meta": _union_payload_meta(len(ordered_events_list), entries_merged, skipped_count, skipped),
        "union": result,
    }


def build_deep_union_from_parsed_traces(parsed_traces_dir: Path | str) -> dict[str, Any]:
    root = Path(parsed_traces_dir)
    if not root.is_dir():
        raise NotADirectoryError(f"parsed_traces path is not a directory: {root}")

    ordered_by_session: list[list[dict[str, Any]]] = []
    session_sources: list[str] = []
    for path in sorted(root.glob("*.json")):
        doc = json.loads(path.read_text())
        ordered = doc.get("ordered_events")
        if isinstance(ordered, list):
            ordered_by_session.append(ordered)
            session_sources.append(path.name)

    acc: dict[str, Any] = {}
    entries_merged, skipped_count, skipped = _merge_sessions_into_acc(
        acc,
        ordered_by_session,
        session_sources=session_sources,
    )
    materialized = _materialize(acc)
    result = materialized if isinstance(materialized, dict) else {}
    return {
        "meta": _union_payload_meta(len(ordered_by_session), entries_merged, skipped_count, skipped),
        "union": result,
    }


def write_deep_union_over_parsed_traces(study_dir: Path | str) -> Path:
    study_path = Path(study_dir)
    parsed_dir = study_path / "parsed_traces"
    payload = build_deep_union_from_parsed_traces(parsed_dir)
    out_path = study_path / OUTPUT_FILENAME
    out_path.write_text(json.dumps(payload, indent=2) + "\n")
    meta = payload["meta"]
    logger.info(
        "Deep union written to %s (%s sessions, %s merged ordered entries, %s skipped)",
        out_path,
        meta["sessions_merged"],
        meta["ordered_event_entries_merged"],
        meta["ordered_event_entries_skipped_schema_mismatch"],
    )
    return out_path
