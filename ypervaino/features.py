from __future__ import annotations

import json
import random
import re
import statistics
from collections import defaultdict
from typing import Any

from ypervaino.config_loader import load_system_knowledge
from ypervaino.embeddings import embedding_dim


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


def _norm_name(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_")


_UUID_PREFIX = re.compile(r"^[0-9a-f]{8}-", re.I)
_SKIP_SKILL_NAMES = frozenset({"unknown", "proxy_node", "finish", "fin"})


def _is_uuidish(value: str) -> bool:
    s = (value or "").strip()
    return bool(s and _UUID_PREFIX.match(s))


def _add_skill_name(skills: set[str], value: str) -> None:
    name = (value or "").strip()
    if not name or _is_uuidish(name):
        return
    if _norm_name(name) in _SKIP_SKILL_NAMES:
        return
    skills.add(name)


def _add_tool_name(tools: set[str], value: str) -> None:
    name = (value or "").strip()
    if not name or _is_uuidish(name):
        return
    tools.add(name)


def _extract_structured_hits(events: list[dict]) -> dict[str, list[str]]:
    skills, tools, agents, nodes, purposes, event_types = set(), set(), set(), set(), set(), set()
    for e in events:
        et = e.get("event_type") or ""
        if et:
            event_types.add(et)
        ev = e.get("event_value") or {}
        if not isinstance(ev, dict):
            continue

        ev_type = str(ev.get("type") or "").lower()
        ev_name = ev.get("name")
        if ev_name:
            if ev_type == "skill" or et == "DEBUG.SKILL_ROUTED":
                _add_skill_name(skills, str(ev_name))
            elif ev_type == "tool" or et == "DEBUG.TOOL_INVOKED":
                _add_tool_name(tools, str(ev_name))

        for key in ("skill_name", "skill", "skill_id"):
            if ev.get(key):
                _add_skill_name(skills, str(ev[key]))
        for key in ("tool_name", "tool"):
            if ev.get(key):
                _add_tool_name(tools, str(ev[key]))
        if ev.get("tool_id") and not ev.get("name"):
            _add_tool_name(tools, str(ev["tool_id"]))
        for key in ("agent_name",):
            if ev.get(key):
                agents.add(str(ev[key]))
        for key in ("node_name", "node", "dialog_node"):
            if ev.get(key):
                nodes.add(str(ev[key]))
        if ev.get("purpose"):
            purposes.add(str(ev["purpose"]))
    return {
        "skills": sorted(skills),
        "tools": sorted(tools),
        "agent_names": sorted(agents),
        "nodes": sorted(nodes),
        "purposes": sorted(purposes),
        "event_types": sorted(event_types),
    }


def _session_outcome(events: list[dict]) -> str:
    transfers = [e for e in events if e.get("event_type") == "CALL_TRANSFER_COMPLETED"]
    if transfers:
        return "transferred"
    for e in events:
        if e.get("event_type") == "SESSION_END":
            status = (_ev(e, "status") or _ev(e, "end_reason") or "").lower()
            if "timeout" in status:
                return "timeout"
            if status:
                return status
    metrics = [e for e in events if e.get("event_type") == "SESSION_METRICS_COMPUTED"]
    if metrics:
        return "completed"
    return "unknown"


def _opening_user_text(events: list[dict]) -> str:
    for e in events:
        if e.get("event_type") != "USER_QUERY":
            continue
        content = (e.get("content") or "").strip()
        if content and "welcome" not in content.lower()[:40]:
            return content
    for e in events:
        if e.get("event_type") == "USER_QUERY" and e.get("content"):
            return str(e["content"])
    return ""


def compute_features(conversation: dict[str, Any], *, include_embedding: bool = True) -> dict[str, Any]:
    events = conversation.get("events") or []
    sk = load_system_knowledge()
    zero_cost = set(sk.get("zero_cost_models") or [])
    price_table = sk.get("price_table") or {}

    user_queries = [e for e in events if e.get("event_type") == "USER_QUERY"]
    llm_success = [e for e in events if e.get("event_type") == "LLM_INVOCATION_SUCCESS"]
    token_rows = [e for e in events if e.get("event_type") == "TOKEN_USAGE_DETAILS"]
    guardrails = [e for e in events if e.get("event_type") == "GUARDRAIL_CHECK"]
    transfers = [e for e in events if e.get("event_type") == "CALL_TRANSFER_COMPLETED"]
    interruptions = [e for e in events if e.get("event_type") == "INTERRUPTION_HANDLER_RESULT"]
    tool_results = [e for e in events if e.get("event_type") == "TOOL_CALL_RESULT"]

    timestamps = [_parse_ts(e.get("timestamp")) for e in events]
    timestamps = [t for t in timestamps if t is not None]
    duration_ms = int((max(timestamps) - min(timestamps)) * 1000) if len(timestamps) >= 2 else 0

    def latencies(purpose: str) -> list[float]:
        return [
            float(_ev(e, "latency_ms") or 0)
            for e in llm_success
            if _ev(e, "purpose") == purpose and _ev(e, "latency_ms")
        ]

    def p95(vals: list[float]) -> float:
        if not vals:
            return 0.0
        if len(vals) >= 2:
            return float(statistics.quantiles(vals, n=20)[-1])
        return float(vals[0])

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
    for e in events:
        if e.get("event_type") != "RESPONSE.FINAL":
            continue
        name = _ev(e, "agent_name")
        if name and (not agent_names or agent_names[-1] != name):
            agent_names.append(name)

    guardrail_triggered = any(
        _ev(e, "would_block") is True or bool(_ev(e, "flagged_categories"))
        for e in guardrails
    )

    searchable_parts = []
    user_utterance_parts = []
    dialog_parts = []
    for e in events:
        if e.get("content"):
            content = str(e["content"])
            searchable_parts.append(content)
            dialog_parts.append(content)
            if e.get("event_type") == "USER_QUERY":
                user_utterance_parts.append(content)
        ev = e.get("event_value")
        if ev:
            searchable_parts.append(json.dumps(ev, default=str))
    searchable_text = "\n".join(searchable_parts).lower()
    dialog_searchable_text = "\n".join(dialog_parts).lower()
    user_turns = [t.lower() for t in user_utterance_parts]
    user_searchable_text = "\n".join(user_turns)

    structured_hits = _extract_structured_hits(events)
    turn_count = len(user_queries)
    if turn_count <= 4:
        length_bucket = "short"
    elif turn_count <= 10:
        length_bucket = "medium"
    else:
        length_bucket = "long"

    outcome = _session_outcome(events)
    outcome_bucket = outcome if outcome in ("transferred", "timeout", "completed") else "other"

    traffic_split_variant = None
    for e in events:
        if e.get("event_type") == "CANARY_BUCKET_DECISION":
            traffic_split_variant = _ev(e, "selected_variant_key")
            break

    opening_text = _opening_user_text(events)
    dim = embedding_dim()
    if include_embedding:
        from ypervaino.embeddings import encode_text
        embedding_opening = encode_text(opening_text) if opening_text else [0.0] * dim
    else:
        embedding_opening = [0.0] * dim

    tool_latencies = [float(_ev(e, "latency") or 0) for e in tool_results if _ev(e, "latency")]

    return {
        "session_id": conversation["session_id"],
        "turn_count": turn_count,
        "session_duration_ms": duration_ms,
        "session_outcome": outcome,
        "outcome_bucket": outcome_bucket,
        "length_bucket": length_bucket,
        "main_stream_model": main_stream_model,
        "main_stream_model_invoked": main_stream_model,
        "main_stream_latency_p95": round(p95(latencies("main_stream")), 2),
        "contextual_query_latency_p95": round(p95(latencies("contextual_query")), 2),
        "router_latency_p95": round(p95(latencies("router")), 2),
        "main_stream_estimated_cost_usd": round(main_stream_cost, 6),
        "tool_invocation_count": len([e for e in events if e.get("event_type") in ("DEBUG.TOOL_INVOKED", "TOOL_CALL_RESULT")]),
        "tool_error_count": len([e for e in events if e.get("event_type") == "TOOL_CALL_ERROR"]),
        "avg_tool_latency_ms": round(statistics.mean(tool_latencies), 2) if tool_latencies else 0.0,
        "transfer_completed": bool(transfers),
        "guardrail_triggered": guardrail_triggered,
        "interruption_count": len(interruptions),
        "agent_path": "→".join(agent_names),
        "structured_hits": structured_hits,
        "searchable_text": searchable_text,
        "dialog_searchable_text": dialog_searchable_text,
        "user_searchable_text": user_searchable_text,
        "user_turns": user_turns,
        "traffic_split_variant": traffic_split_variant,
        "opening_text": opening_text,
        "embedding_opening": embedding_opening,
        "opening_intent_class": "unknown",
        "opening_intent_score": 0.0,
    }


def stratum_key(fv: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(fv.get("opening_intent_class") or "unknown"),
        str(fv.get("outcome_bucket") or "other"),
        str(fv.get("length_bucket") or "medium"),
    )
