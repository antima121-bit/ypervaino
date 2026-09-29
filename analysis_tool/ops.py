"""Ordered-event predicate ops and cohort accumulated metrics over parsed_traces."""

from __future__ import annotations

import json
import math
import re
import statistics
from pathlib import Path
from typing import Any, Sequence

from trace_parser import VOICE_SESSION_LATENCY_FIELDS

ORDERED_EVENT_TYPES = frozenset(
    {
        "USER_QUERY",
        "RESPONSE.FINAL",
        "TOOL_CALL_RESULT",
        "TOOL_CALL_ERROR",
        "DEBUG.TOOL_INVOKED",
        "DIALOG_FLOW_TRANSITION_COMPLETED",
        "LLM_INVOCATION_SUCCESS",
        "LLM_INVOCATION_ERROR",
        "LLM_CONFIG_RESOLVED",
    }
)

VOICE_LATENCY_P95_KEYS = frozenset(
    k
    for k in VOICE_SESSION_LATENCY_FIELDS
    if k not in {"total_events_count", "no_of_llm_decision_calls", "no_of_yield_calls"}
)

VOICE_COUNT_KEYS = frozenset(
    {"total_events_count", "no_of_llm_decision_calls", "no_of_yield_calls"}
)

TOKEN_METRIC_KEYS = frozenset(
    {"input_tokens", "output_tokens", "total_tokens", "cache_read"}
)

COMPARE_OPS = frozenset({"==", "!=", "<", "<=", ">", ">=", "in", "exists"})

_INLINE_FLAG_TOKENS: tuple[tuple[str, int], ...] = (
    ("(?i)", re.IGNORECASE),
    ("(?m)", re.MULTILINE),
    ("(?s)", re.DOTALL),
    ("(?x)", re.VERBOSE),
)


def compile_regex_pattern(pattern: str) -> re.Pattern[str]:
    """Compile LLM/authored patterns; inline (?i) etc. may appear mid-string."""
    flags = 0
    stripped = pattern
    for token, bit in _INLINE_FLAG_TOKENS:
        while token in stripped:
            flags |= bit
            stripped = stripped.replace(token, "", 1)
    stripped = stripped.strip()
    if not stripped:
        raise re.error("empty regex pattern after removing inline flags")
    return re.compile(stripped, flags)


def _ordered_events(parsed_trace: dict[str, Any]) -> list[dict[str, Any]]:
    events = parsed_trace.get("ordered_events")
    if not isinstance(events, list):
        return []
    return [e for e in events if isinstance(e, dict)]


def _coerce_numeric(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return float(value)
    if isinstance(value, float):
        return value
    return None


def _is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _resolve_path(obj: Any, keys: Sequence[str]) -> Any | None:
    cur = obj
    for key in keys:
        if not isinstance(cur, dict) or key not in cur:
            return None
        cur = cur[key]
    return cur


def _compare_scalar(left: Any, right: Any, op: str) -> bool:
    if op == "exists":
        return True
    if op not in COMPARE_OPS:
        raise ValueError(f"Unsupported comparison op: {op!r}")

    if op == "in":
        if not isinstance(right, (list, tuple, set, frozenset)):
            raise ValueError("op 'in' requires value to be a list or set")
        if isinstance(left, bool):
            return left in right
        num_left = _coerce_numeric(left)
        if num_left is not None:
            normalized = []
            for item in right:
                n = _coerce_numeric(item)
                normalized.append(n if n is not None else item)
            return num_left in normalized or left in right
        return left in right

    num_left = _coerce_numeric(left)
    num_right = _coerce_numeric(right)
    if num_left is not None and num_right is not None:
        left_cmp, right_cmp = num_left, num_right
    else:
        left_cmp, right_cmp = left, right

    if op == "==":
        return left_cmp == right_cmp
    if op == "!=":
        return left_cmp != right_cmp
    if op == "<":
        return left_cmp < right_cmp
    if op == "<=":
        return left_cmp <= right_cmp
    if op == ">":
        return left_cmp > right_cmp
    if op == ">=":
        return left_cmp >= right_cmp
    raise ValueError(f"Unsupported comparison op: {op!r}")


def _path_predicate_on_payload(payload: Any, path_keys: Sequence[str], value: Any, op: str) -> bool:
    if not path_keys:
        return False
    resolved = _resolve_path(payload, path_keys)
    if resolved is None:
        return False
    if op == "exists":
        return True
    if not _is_scalar(resolved) or isinstance(resolved, dict) or isinstance(resolved, list):
        return False
    return _compare_scalar(resolved, value, op)


def event_exists(parsed_trace: dict[str, Any], event_name: str) -> bool:
    for item in _ordered_events(parsed_trace):
        if event_name in item:
            return True
    return False


def meta_value_operation(
    parsed_trace: dict[str, Any],
    path: Sequence[str],
    value: Any,
    op: str,
) -> bool:
    if not path:
        raise ValueError("path must be non-empty")
    if op not in COMPARE_OPS:
        raise ValueError(f"Unsupported op: {op!r}")

    event_type = path[0]
    path_keys = path[1:]

    for item in _ordered_events(parsed_trace):
        if event_type not in item:
            continue
        payload = item[event_type]
        if op == "exists" and not path_keys:
            return True
        if _path_predicate_on_payload(payload, path_keys, value, op):
            return True
    return False


def regex(parsed_trace: dict[str, Any], turn_type: str, pattern: str) -> bool:
    if turn_type not in {"user_turn", "bot_turn"}:
        raise ValueError("turn_type must be 'user_turn' or 'bot_turn'")
    event_key = "USER_QUERY" if turn_type == "user_turn" else "RESPONSE.FINAL"
    compiled = compile_regex_pattern(pattern)
    for item in _ordered_events(parsed_trace):
        if event_key not in item:
            continue
        block = item[event_key]
        if not isinstance(block, dict):
            continue
        content = block.get("content")
        if isinstance(content, str) and content and compiled.search(content):
            return True
    return False


def _normalize_seq(seq: Sequence[Any]) -> tuple[str, tuple[str, ...] | None, Any | None, str | None]:
    if isinstance(seq, str):
        return seq, None, None, None
    if len(seq) == 1:
        only = seq[0]
        if isinstance(only, str):
            return only, None, None, None
        raise ValueError(f"Invalid seq (single element must be event type string): {seq!r}")
    if len(seq) == 4:
        event_type, keys, val, compare_op = seq[0], seq[1], seq[2], seq[3]
        if not isinstance(event_type, str):
            raise ValueError(f"Invalid seq event_type: {seq!r}")
        if not isinstance(compare_op, str):
            raise ValueError(f"Invalid seq op: {seq!r}")
        key_tuple: tuple[str, ...]
        if keys is None:
            key_tuple = ()
        elif isinstance(keys, (list, tuple)):
            key_tuple = tuple(str(k) for k in keys)
        else:
            raise ValueError(f"Invalid seq keys: {seq!r}")
        return event_type, key_tuple, val, compare_op
    raise ValueError(f"Invalid seq length (want 1 or 4): {seq!r}")


def _item_matches_seq(item: dict[str, Any], seq: Sequence[Any]) -> bool:
    event_type, path_keys, value, compare_op = _normalize_seq(seq)
    if event_type not in item:
        return False
    if path_keys is None and compare_op is None:
        return True
    payload = item[event_type]
    assert path_keys is not None and compare_op is not None
    return _path_predicate_on_payload(payload, path_keys, value, compare_op)


def is_ordered_seq_present(parsed_trace: dict[str, Any], sequences: Sequence[Sequence[Any]]) -> bool:
    events = _ordered_events(parsed_trace)
    start = 0
    for seq in sequences:
        matched = False
        for j in range(start, len(events)):
            if _item_matches_seq(events[j], seq):
                start = j + 1
                matched = True
                break
        if not matched:
            return False
    return True


def _is_valid_number(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return False
    return isinstance(value, (int, float))


def _append_numeric(pool: list[float], value: Any) -> None:
    if not _is_valid_number(value):
        return
    pool.append(float(value))


def _metric_kind(event_type: str, key: str) -> str | None:
    if event_type == "CALL_TRANSFER_COMPLETED":
        return "transfer_rate"
    if event_type == "TOKEN_USAGE_DETAILS" and key in TOKEN_METRIC_KEYS:
        return "token"
    if event_type == "VOICE_SESSION_LATENCY_METRICS":
        if key in VOICE_COUNT_KEYS:
            return "count"
        if key in VOICE_LATENCY_P95_KEYS:
            return "p95"
    if key in {"latency", "latency_ms", "turn_latency_ms"}:
        return "p95"
    if key.endswith("_ms") or "latency" in key:
        return "p95"
    return None


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    n = len(ordered)
    rank = math.ceil(0.95 * n) - 1
    idx = min(n - 1, max(0, rank))
    return ordered[idx]


def _token_stats(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"total": None, "mean": None, "std": None}
    total = sum(values)
    mean = statistics.mean(values)
    std = statistics.pstdev(values) if len(values) > 1 else 0.0
    return {"total": total, "mean": mean, "std": std}


def _count_stats(values: list[float]) -> dict[str, float | None]:
    return _token_stats(values)


def compute_accumulated_cohort_metrics(parsed_traces_dir: Path | str) -> dict[str, Any]:
    root = Path(parsed_traces_dir)
    if not root.is_dir():
        raise NotADirectoryError(f"Not a directory: {root}")

    pools: dict[tuple[str, str], list[float]] = {}
    sessions_total = 0
    transfer_sessions = 0

    for path in sorted(root.glob("*.json")):
        doc = json.loads(path.read_text())
        sessions_total += 1
        accumulated = doc.get("accumulated_events")
        if not isinstance(accumulated, dict):
            continue

        if accumulated.get("CALL_TRANSFER_COMPLETED") == {"exists": True}:
            transfer_sessions += 1

        for event_type, bucket in accumulated.items():
            if event_type == "CALL_TRANSFER_COMPLETED":
                continue
            if not isinstance(bucket, dict):
                continue
            for key, series in bucket.items():
                if not isinstance(series, list):
                    continue
                pool_key = (event_type, key)
                pool = pools.setdefault(pool_key, [])
                for val in series:
                    _append_numeric(pool, val)

    metrics: dict[str, Any] = {}
    for (event_type, key), pool in sorted(pools.items()):
        metric_key = f"{event_type}.{key}"
        kind = _metric_kind(event_type, key)
        if kind == "p95":
            metrics[metric_key] = {"p95": _p95(pool), "n": len(pool)}
        elif kind in {"token", "count"}:
            stats = _token_stats(pool)
            stats["n"] = len(pool)
            metrics[metric_key] = stats
        elif kind is None and pool:
            metrics[metric_key] = {"p95": _p95(pool), "n": len(pool)}

    if sessions_total:
        metrics["CALL_TRANSFER_COMPLETED.exists"] = {
            "session_rate": transfer_sessions / sessions_total,
            "sessions_with_transfer": transfer_sessions,
            "sessions_total": sessions_total,
        }

    return {
        "meta": {
            "parsed_traces_dir": str(root),
            "sessions_scanned": sessions_total,
            "pooled_numeric_excludes": "null, none, non-numeric, bool",
        },
        "metrics": metrics,
    }


def write_accumulated_cohort_metrics(study_dir: Path | str, *, filename: str = "accumulated_cohort_metrics.json") -> Path:
    study_path = Path(study_dir)
    parsed_dir = study_path / "parsed_traces"
    payload = compute_accumulated_cohort_metrics(parsed_dir)
    out = study_path / filename
    out.write_text(json.dumps(payload, indent=2) + "\n")
    return out
