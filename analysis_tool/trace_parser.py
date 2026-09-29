"""Parse BotProbe log_traces into transcript, ordered_events, and accumulated_events."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

ALLOWED_EVENT_TYPES = frozenset(
    {
        "USER_QUERY",
        "RESPONSE.FINAL",
        "TOOL_CALL_RESULT",
        "TOOL_CALL_ERROR",
        "DEBUG.TOOL_INVOKED",
        "DIALOG_FLOW_TRANSITION_COMPLETED",
        "QUERY_PREPROCESSING_DONE",
        "POST_GRAPH_PROCESSING_DONE",
        "LLM_INVOCATION_SUCCESS",
        "LLM_INVOCATION_ERROR",
        "LLM_CONFIG_RESOLVED",
        "VOICE_SESSION_LATENCY_METRICS",
        "CALL_TRANSFER_COMPLETED",
        "TOKEN_USAGE_DETAILS",
    }
)

VOICE_SESSION_LATENCY_FIELDS = (
    "first_token_generation_latency_ms",
    "first_token_sent_latency_ms",
    "query_time_in_queue_ms",
    "contextual_query_latency_ms",
    "router_and_contextual_combined_latency_ms",
    "skill_node_preprocessing_latency_ms",
    "tool_call_latency_ms",
    "tool_decision_latency_ms",
    "post_tool_response_latency_ms",
    "first_token_by_llm_latency_ms",
    "router_pickup_latency_ms",
    "knowledge_agent_first_token_sent_latency_ms",
    "total_events_count",
    "routed_to_sub_agent_latency_ms",
    "no_of_llm_decision_calls",
    "yield_decision_latency_ms",
    "no_of_yield_calls",
)


@dataclass
class ParseResult:
    ordered: dict[str, Any] | None = None
    accumulated: dict[str, Any] | None = None
    transcript: dict[str, str] | None = None
    call_transfer_exists: bool = False


@dataclass
class AccumulatedEvents:
    buckets: dict[str, dict[str, list[Any]]] = field(default_factory=dict)
    call_transfer_exists: bool = False

    def append(self, event_type: str, values: dict[str, Any]) -> None:
        bucket = self.buckets.setdefault(event_type, {})
        for key, val in values.items():
            bucket.setdefault(key, []).append(val)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = dict(self.buckets)
        if self.call_transfer_exists:
            out["CALL_TRANSFER_COMPLETED"] = {"exists": True}
        return out


def _event_value(event: dict[str, Any]) -> dict[str, Any]:
    raw = event.get("event_value")
    return raw if isinstance(raw, dict) else {}


def _content(event: dict[str, Any]) -> str:
    c = event.get("content")
    return c if isinstance(c, str) else ""


def _parse_json_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return {}
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {"_value": parsed}
        except json.JSONDecodeError:
            return {"_raw": value}
    return {"_value": value}


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    return None


def _as_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def resolve_event_type(event: dict[str, Any]) -> str | None:
    et = event.get("event_type")
    ev = _event_value(event)
    logged = ev.get("logged_event_type")
    if isinstance(et, str) and et in ALLOWED_EVENT_TYPES:
        return et
    if isinstance(logged, str) and logged in ALLOWED_EVENT_TYPES:
        return logged
    return None


def _skip_scrubbed_duplicate(event: dict[str, Any], event_type: str) -> bool:
    """Ignore EBL/file-sink rows that repeat an event type with placeholder content."""
    if _content(event) != "event_flushed_to_file":
        return False
    outer = event.get("event_type")
    if outer == event_type:
        return False
    return outer == "EBL_EVENT_FLUSHED" or outer != event_type


def parse_user_query(event: dict[str, Any]) -> ParseResult:
    ev = _event_value(event)
    return ParseResult(
        ordered={
            "USER_QUERY": {
                "event_value": {"query_language": _as_str(ev.get("query_language"))},
                "content": _content(event),
            }
        },
        transcript={"user": _content(event)},
    )


def parse_response_final(event: dict[str, Any]) -> ParseResult:
    ev = _event_value(event)
    latency = _as_float(ev.get("latency"))
    return ParseResult(
        ordered={
            "RESPONSE.FINAL": {
                "event_value": {"agent_name": _as_str(ev.get("agent_name"))},
                "content": _content(event),
            }
        },
        accumulated={"latency": latency} if latency is not None else None,
        transcript={"bot": _content(event)},
    )


def parse_tool_call_result(event: dict[str, Any]) -> ParseResult:
    ev = _event_value(event)
    tool_name = _as_str(ev.get("tool_name")) or "unknown_tool"
    latency = _as_float(ev.get("latency"))
    return ParseResult(
        ordered={
            "TOOL_CALL_RESULT": {
                tool_name: {
                    "tool_args": _parse_json_dict(ev.get("tool_args")),
                    "result": _parse_json_dict(ev.get("result")),
                }
            }
        },
        accumulated={"latency": latency} if latency is not None else None,
    )


def parse_tool_call_error(event: dict[str, Any]) -> ParseResult:
    ev = _event_value(event)
    return ParseResult(
        ordered={
            "TOOL_CALL_ERROR": {
                "event_value": {"tool_name": _as_str(ev.get("tool_name"))},
            }
        }
    )


def parse_debug_tool_invoked(event: dict[str, Any]) -> ParseResult:
    ev = _event_value(event)
    name = _as_str(ev.get("name")) or "unknown_tool"
    tool_input = ev.get("input")
    if not isinstance(tool_input, dict):
        tool_input = _parse_json_dict(tool_input)
    return ParseResult(
        ordered={"DEBUG.TOOL_INVOKED": {name: {"input": tool_input}}},
    )


def parse_dialog_flow_transition_completed(event: dict[str, Any]) -> ParseResult:
    ev = _event_value(event)
    return ParseResult(
        ordered={
            "DIALOG_FLOW_TRANSITION_COMPLETED": {
                "event_value": {
                    "source_node": _as_str(ev.get("source_node")),
                    "target_node": _as_str(ev.get("target_node")),
                }
            }
        }
    )


def parse_query_preprocessing_done(event: dict[str, Any]) -> ParseResult:
    ev = _event_value(event)
    latency = _as_float(ev.get("latency"))
    return ParseResult(
        accumulated={"latency": latency} if latency is not None else None,
    )


def parse_post_graph_processing_done(event: dict[str, Any]) -> ParseResult:
    ev = _event_value(event)
    latency = _as_float(ev.get("latency"))
    return ParseResult(
        accumulated={"latency": latency} if latency is not None else None,
    )


def parse_llm_invocation_success(event: dict[str, Any]) -> ParseResult:
    ev = _event_value(event)
    accum: dict[str, Any] = {}
    if (v := _as_float(ev.get("latency_ms"))) is not None:
        accum["latency_ms"] = v
    if (v := _as_float(ev.get("turn_latency_ms"))) is not None:
        accum["turn_latency_ms"] = v
    return ParseResult(
        ordered={
            "LLM_INVOCATION_SUCCESS": {
                "event_value": {
                    "model_id": _as_str(ev.get("model_id")),
                    "is_fallback": _as_bool(ev.get("is_fallback")),
                    "purpose": _as_str(ev.get("purpose")),
                    "is_tool_call_decision": _as_bool(ev.get("is_tool_call_decision")),
                }
            }
        },
        accumulated=accum or None,
    )


def parse_llm_invocation_error(event: dict[str, Any]) -> ParseResult:
    ev = _event_value(event)
    return ParseResult(
        ordered={
            "LLM_INVOCATION_ERROR": {
                "event_value": {
                    "model_id": _as_str(ev.get("model_id")),
                    "is_fallback": _as_bool(ev.get("is_fallback")),
                    "purpose": _as_str(ev.get("purpose")),
                    "error_type": _as_str(ev.get("error_type")),
                }
            }
        }
    )


def parse_llm_config_resolved(event: dict[str, Any]) -> ParseResult:
    ev = _event_value(event)
    return ParseResult(
        ordered={
            "LLM_CONFIG_RESOLVED": {
                "event_value": {
                    "purpose": _as_str(ev.get("purpose")),
                    "final_model_id": _as_str(ev.get("final_model_id")),
                }
            }
        }
    )


def parse_voice_session_latency_metrics(event: dict[str, Any]) -> ParseResult:
    ev = _event_value(event)
    accum = {key: _as_float(ev.get(key)) for key in VOICE_SESSION_LATENCY_FIELDS}
    return ParseResult(accumulated=accum)


def parse_call_transfer_completed(_event: dict[str, Any]) -> ParseResult:
    return ParseResult(call_transfer_exists=True)


def parse_token_usage_details(event: dict[str, Any]) -> ParseResult:
    ev = _event_value(event)
    accum = {
        "input_tokens": _as_int(ev.get("input_tokens")),
        "output_tokens": _as_int(ev.get("output_tokens")),
        "total_tokens": _as_int(ev.get("total_tokens")),
        "cache_read": _as_int(ev.get("cache_read")),
    }
    return ParseResult(accumulated=accum)


EVENT_PARSERS: dict[str, Callable[[dict[str, Any]], ParseResult]] = {
    "USER_QUERY": parse_user_query,
    "RESPONSE.FINAL": parse_response_final,
    "TOOL_CALL_RESULT": parse_tool_call_result,
    "TOOL_CALL_ERROR": parse_tool_call_error,
    "DEBUG.TOOL_INVOKED": parse_debug_tool_invoked,
    "DIALOG_FLOW_TRANSITION_COMPLETED": parse_dialog_flow_transition_completed,
    "QUERY_PREPROCESSING_DONE": parse_query_preprocessing_done,
    "POST_GRAPH_PROCESSING_DONE": parse_post_graph_processing_done,
    "LLM_INVOCATION_SUCCESS": parse_llm_invocation_success,
    "LLM_INVOCATION_ERROR": parse_llm_invocation_error,
    "LLM_CONFIG_RESOLVED": parse_llm_config_resolved,
    "VOICE_SESSION_LATENCY_METRICS": parse_voice_session_latency_metrics,
    "CALL_TRANSFER_COMPLETED": parse_call_transfer_completed,
    "TOKEN_USAGE_DETAILS": parse_token_usage_details,
}


def dispatch_parse_event(event_type: str, event: dict[str, Any]) -> ParseResult:
    if event_type not in ALLOWED_EVENT_TYPES:
        raise ValueError(f"Event type not in allowed schema: {event_type!r}")
    parser = EVENT_PARSERS.get(event_type)
    if parser is None:
        raise NotImplementedError(f"No parser implemented for event type {event_type!r}")
    return parser(event)


def _event_sort_key(event: dict[str, Any], index: int) -> tuple:
    ts = event.get("timestamp")
    if isinstance(ts, str):
        try:
            normalized = ts.replace("Z", "+00:00")
            return (0, datetime.fromisoformat(normalized), index)
        except ValueError:
            pass
    return (1, index)


def parse_trace_document(trace: dict[str, Any]) -> dict[str, Any]:
    events = trace.get("events")
    if not isinstance(events, list):
        raise ValueError("Trace document missing 'events' list")

    indexed = list(enumerate(events))
    indexed.sort(key=lambda pair: _event_sort_key(pair[1], pair[0]))

    transcript: list[dict[str, str]] = []
    ordered_events: list[dict[str, Any]] = []
    accumulated = AccumulatedEvents()

    for _idx, raw in indexed:
        if not isinstance(raw, dict):
            continue
        event_type = resolve_event_type(raw)
        if event_type is None:
            continue
        if _skip_scrubbed_duplicate(raw, event_type):
            continue

        result = dispatch_parse_event(event_type, raw)

        if result.transcript:
            transcript.append(result.transcript)
        if result.ordered:
            ordered_events.append(result.ordered)
        if result.accumulated:
            accumulated.append(event_type, result.accumulated)
        if result.call_transfer_exists:
            accumulated.call_transfer_exists = True

    return {
        "Transcript": transcript,
        "ordered_events": ordered_events,
        "accumulated_events": accumulated.to_dict(),
    }


def parse_log_traces(log_traces_dir: Path | str) -> dict[str, dict[str, Any]]:
    """Parse every *.json trace under log_traces_dir; key = session id (filename stem)."""
    root = Path(log_traces_dir)
    if not root.is_dir():
        raise NotADirectoryError(f"log_traces path is not a directory: {root}")

    out: dict[str, dict[str, Any]] = {}
    for path in sorted(root.glob("*.json")):
        session_id = path.stem
        trace = json.loads(path.read_text())
        out[session_id] = parse_trace_document(trace)
    logger.info("Parsed %s trace file(s) from %s", len(out), root)
    return out


def write_parsed_traces(
    log_traces_dir: Path | str,
    output_dir: Path | str,
) -> dict[str, Path]:
    """Write parsed_traces/<session_id>.json next to or under output_dir."""
    parsed = parse_log_traces(log_traces_dir)
    out_root = Path(output_dir) / "parsed_traces"
    out_root.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    for session_id, doc in parsed.items():
        path = out_root / f"{session_id}.json"
        path.write_text(json.dumps(doc, indent=2) + "\n")
        written[session_id] = path
    logger.info("Wrote %s parsed trace file(s) to %s", len(written), out_root)
    return written


if __name__ == "__main__":
    import argparse
    import sys

    from log_setup import configure_logging

    configure_logging(logging.INFO)
    ap = argparse.ArgumentParser(description="Parse log_traces into structured session docs.")
    ap.add_argument("log_traces_dir", type=Path, help="Directory of BotProbe trace JSON files")
    ap.add_argument(
        "--study-dir",
        type=Path,
        default=None,
        help="Study folder; writes parsed_traces/ inside it (default: parent of log_traces_dir)",
    )
    args = ap.parse_args()
    study_dir = args.study_dir or args.log_traces_dir.parent
    write_parsed_traces(args.log_traces_dir, study_dir)
    sys.exit(0)
