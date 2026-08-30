from __future__ import annotations

import json
import re
import statistics
from typing import Any

from ypervaino.config_loader import load_system_knowledge


def _ev(e: dict, key: str, default=None):
    val = e.get("event_value") or {}
    if isinstance(val, dict) and key in val:
        return val[key]
    return e.get(key, default)


def _parse_ts(ts: Any) -> float | None:
    if not ts:
        return None
    if isinstance(ts, str):
        try:
            from datetime import datetime
            return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
        except Exception:
            return None
    return None


def compute_features(conversation: dict[str, Any]) -> dict[str, Any]:
    events = conversation.get("events") or []
    sk = load_system_knowledge()
    zero_cost = set(sk.get("zero_cost_models") or [])
    price_table = sk.get("price_table") or {}

    user_queries = [e for e in events if e.get("event_type") == "USER_QUERY"]
    responses = [e for e in events if e.get("event_type") == "RESPONSE.FINAL"]
    llm_success = [e for e in events if e.get("event_type") == "LLM_INVOCATION_SUCCESS"]
    token_rows = [e for e in events if e.get("event_type") == "TOKEN_USAGE_DETAILS"]
    tool_results = [e for e in events if e.get("event_type") == "TOOL_CALL_RESULT"]
    guardrails = [e for e in events if e.get("event_type") == "GUARDRAIL_CHECK"]
    transfers = [e for e in events if e.get("event_type") == "CALL_TRANSFER_COMPLETED"]
    interruptions = [e for e in events if e.get("event_type") == "INTERRUPTION_HANDLER_RESULT"]

    timestamps = [_parse_ts(e.get("timestamp")) for e in events]
    timestamps = [t for t in timestamps if t is not None]
    duration_ms = int((max(timestamps) - min(timestamps)) * 1000) if len(timestamps) >= 2 else 0

    main_stream_latencies = [
        float(_ev(e, "latency_ms") or 0)
        for e in llm_success
        if _ev(e, "purpose") == "main_stream" and _ev(e, "latency_ms")
    ]
    main_stream_p95 = (
        statistics.quantiles(main_stream_latencies, n=20)[-1]
        if len(main_stream_latencies) >= 2
        else (main_stream_latencies[0] if main_stream_latencies else 0.0)
    )

    main_stream_model = None
    for e in reversed([x for x in events if x.get("event_type") == "LLM_CONFIG_RESOLVED"]):
        if _ev(e, "purpose") == "main_stream":
            main_stream_model = _ev(e, "final_model_id")
            break
    if not main_stream_model:
        for e in reversed(llm_success):
            if _ev(e, "purpose") == "main_stream":
                main_stream_model = _ev(e, "model_id")
                break

    def token_cost_usd(model_id: str, inp: int, out: int) -> float:
        if not model_id or model_id in zero_cost:
            return 0.0
        row = price_table.get(model_id) or {}
        inp_rate = float(row.get("input_usd_per_million") or 0) / 1_000_000
        out_rate = float(row.get("output_usd_per_million") or 0) / 1_000_000
        return inp * inp_rate + out * out_rate

    main_stream_cost = 0.0
    for e in token_rows:
        if _ev(e, "purpose") != "main_stream":
            continue
        main_stream_cost += token_cost_usd(
            _ev(e, "model_id") or "",
            int(_ev(e, "input_tokens") or 0),
            int(_ev(e, "output_tokens") or 0),
        )

    agent_names = []
    for e in responses:
        name = _ev(e, "agent_name")
        if name and (not agent_names or agent_names[-1] != name):
            agent_names.append(name)

    guardrail_triggered = any(
        _ev(e, "would_block") is True or (_ev(e, "flagged_categories") or [])
        for e in guardrails
    )

    searchable_parts = []
    for e in events:
        if e.get("content"):
            searchable_parts.append(str(e["content"]))
        ev = e.get("event_value")
        if ev:
            searchable_parts.append(json.dumps(ev, default=str))
    searchable_text = "\n".join(searchable_parts).lower()

    turn_count = len(user_queries)
    if turn_count <= 4:
        length_bucket = "short"
    elif turn_count <= 10:
        length_bucket = "medium"
    else:
        length_bucket = "long"

    if transfers:
        outcome = "transferred"
        outcome_bucket = "transferred"
    else:
        outcome = "completed"
        outcome_bucket = "completed"

    return {
        "session_id": conversation["session_id"],
        "turn_count": turn_count,
        "session_duration_ms": duration_ms,
        "session_outcome": outcome,
        "outcome_bucket": outcome_bucket,
        "length_bucket": length_bucket,
        "main_stream_model": main_stream_model,
        "main_stream_model_invoked": main_stream_model,
        "main_stream_latency_p95": round(main_stream_p95, 2),
        "main_stream_estimated_cost_usd": round(main_stream_cost, 6),
        "tool_invocation_count": len([e for e in events if e.get("event_type") in ("DEBUG.TOOL_INVOKED", "TOOL_CALL_RESULT")]),
        "tool_error_count": len([e for e in events if e.get("event_type") == "TOOL_CALL_ERROR"]),
        "transfer_completed": bool(transfers),
        "guardrail_triggered": guardrail_triggered,
        "interruption_count": len(interruptions),
        "agent_path": "→".join(agent_names),
        "searchable_text": searchable_text,
        "opening_intent_class": classify_opening_intent(searchable_text, agent_names),
        "opening_intent_score": 1.0,
    }


def classify_opening_intent(text: str, agents: list[str]) -> str:
    rules = [
        ("transfer", [r"\btransfer\b", r"\bagent\b", r"\brepresentative\b"]),
        ("billing", [r"\bbill\b", r"\bpayment\b", r"\bcharge\b"]),
        ("appointment", [r"\bappointment\b", r"\bschedule\b", r"\breschedule\b"]),
        ("support", [r"\bhelp\b", r"\bproblem\b", r"\bissue\b"]),
    ]
    first_chunk = text[:800]
    best = ("unknown", 0)
    for intent, patterns in rules:
        score = sum(1 for p in patterns if re.search(p, first_chunk))
        if score > best[1]:
            best = (intent, score)
    return best[0] if best[1] >= 1 else "unknown"
