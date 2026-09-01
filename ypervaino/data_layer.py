from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any

from pymongo import MongoClient

from fetch_filtered_session_ids import fetch_session_ids, load_mongo_env
from lookup_session import resolve_voice_id
from ypervaino.settings import (
    BOT_API_BASE_URL,
    BOTPROBE_TRACE_BASE_URL,
    BOTPROBE_TRACE_ENV,
    PRODUCTION_SERVICE_TOKEN,
)
from ypervaino.log import get_logger

_log = get_logger("data_layer")


def parse_dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def list_tenants(mongo_uri: str, db_name: str) -> list[str]:
    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=15000)
    try:
        tenants = client[db_name].AssistantSession.distinct("tenant")
        return sorted(t for t in tenants if t and t != "None")
    finally:
        client.close()


def list_assistants(mongo_uri: str, db_name: str, tenant: str) -> list[dict[str, Any]]:
    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=15000)
    try:
        db = client[db_name]
        pipeline = [
            {"$match": {"tenant": tenant, "assistant_origin_id": {"$ne": None}}},
            {"$group": {
                "_id": "$assistant_origin_id",
                "count": {"$sum": 1},
                "last_start": {"$max": "$start_time"},
            }},
            {"$sort": {"count": -1}},
            {"$limit": 200},
        ]
        out = []
        for row in db.AssistantSession.aggregate(pipeline, maxTimeMS=15000):
            oid = row["_id"]
            out.append({
                "assistant_origin_id": oid,
                "label": f"{oid} ({row['count']} sessions)",
                "published_versions": [],
            })
        return out
    finally:
        client.close()


def fetch_session_id_list(
    tenant: str,
    assistant_origin_id: str,
    channel: str,
    start: datetime,
    end: datetime,
    assistant_id: str | None = None,
    limit: int | None = None,
) -> list[str]:
    _log.debug(
        "mongo session query tenant=%s assistant=%s channel=%s %s→%s limit=%s",
        tenant, assistant_origin_id, channel, start.isoformat(), end.isoformat(), limit,
    )
    env = load_mongo_env()
    client = MongoClient(env["MONGO_URI"], serverSelectionTimeoutMS=15000)
    try:
        ids = fetch_session_ids(
            client[env["MONGO_DB_NAME"]],
            tenant,
            assistant_origin_id,
            channel,
            start,
            end,
            assistant_id=assistant_id,
            limit=limit,
        )
        _log.info("mongo returned %d session ids", len(ids))
        return ids
    finally:
        client.close()


def fetch_trace(session_uuid: str) -> dict[str, Any]:
    q = urllib.parse.urlencode({
        "session_id": session_uuid,
        "env": BOTPROBE_TRACE_ENV,
    })
    url = f"{BOTPROBE_TRACE_BASE_URL.rstrip('/')}/trace?{q}"
    _log.debug("fetching trace session=%s env=%s", session_uuid, BOTPROBE_TRACE_ENV)
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())


def fetch_blueprint(tenant: str, origin_id: str, channel: str = "voice", runtime_mode: str = "DEBUG") -> dict[str, Any]:
    _log.info("fetching blueprint tenant=%s origin=%s channel=%s", tenant, origin_id, channel)
    url = f"{BOT_API_BASE_URL.rstrip('/')}/service/va-blueprint/extract_blueprint"
    body = json.dumps({
        "tenant": tenant,
        "origin_id": origin_id,
        "channel": channel,
        "runtime_mode": runtime_mode,
    }).encode()
    headers = {
        "Content-Type": "application/json",
        "X-DTS-SCHEMA": tenant,
        "User-Agent": "ypervaino/1.0",
    }
    if PRODUCTION_SERVICE_TOKEN:
        headers["Authorization"] = f"Bearer {PRODUCTION_SERVICE_TOKEN}"
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        _log.warning("blueprint fetch failed: %s", e)
        return {
            "assistant_info": {
                "orchestration_type": "unknown",
                "skill_list": [],
                "_fetch_error": str(e),
            }
        }
    if isinstance(data, dict) and "data" in data:
        return data["data"]
    return data


def dedupe_events(events: list[dict[str, Any]], reconnects: int = 0) -> list[dict[str, Any]]:
    seen_session_end = False
    kept = []
    for e in events:
        if e.get("event_type") == "SESSION_END":
            if seen_session_end:
                continue
            seen_session_end = True
        kept.append(e)
    return kept


def materialize_conversation(session_uuid: str, trace: dict[str, Any], reconnects: int = 0) -> dict[str, Any]:
    events = dedupe_events(trace.get("events", []), reconnects)
    events.sort(key=lambda e: e.get("timestamp") or "")

    by_request: dict[str, list[dict]] = {}
    for e in events:
        rid = e.get("request_id")
        if rid:
            by_request.setdefault(rid, []).append(e)

    turn_rows: list[tuple[str, dict[str, Any]]] = []
    for rid, evs in by_request.items():
        user_q = next((x for x in evs if x.get("event_type") == "USER_QUERY"), None)
        bot_r = next((x for x in evs if x.get("event_type") == "RESPONSE.FINAL"), None)
        if user_q or bot_r:
            turn_ts = min((x.get("timestamp") or "") for x in evs) if evs else ""
            turn_rows.append((turn_ts, {
                "request_id": rid,
                "user": (user_q or {}).get("content") or "",
                "bot": (bot_r or {}).get("content") or "",
                "agent_name": ((bot_r or {}).get("event_value") or {}).get("agent_name"),
            }))

    turn_rows.sort(key=lambda row: row[0])
    turns = [row[1] for row in turn_rows]

    transcript: list[dict[str, str]] = []
    for turn in turns:
        if turn["user"]:
            transcript.append({"speaker": "User", "text": turn["user"]})
        if turn["bot"]:
            transcript.append({"speaker": "Bot", "text": turn["bot"]})

    return {
        "session_id": session_uuid,
        "internal_session_id": trace.get("session_id"),
        "events": events,
        "turns": turns,
        "transcript": transcript,
        "reconnects": reconnects,
    }


def load_or_fetch_conversation(store, session_uuid: str) -> dict[str, Any]:
    cache = store.traces_dir / f"{session_uuid}.json"
    if cache.exists():
        _log.debug("trace cache hit session=%s", session_uuid)
        return store.read_json(cache)
    _log.debug("trace cache miss session=%s → BotProbe", session_uuid)
    trace = fetch_trace(session_uuid)
    conv = materialize_conversation(session_uuid, trace)
    store.write_json(cache, conv)
    return conv


def summarize_blueprint(bp: dict[str, Any]) -> dict[str, Any]:
    info = bp.get("assistant_info") or {}
    skills_raw = info.get("skill_list") or []
    skills = []
    tools = set()
    for sk in skills_raw:
        name = sk.get("name") or sk.get("id") or "unknown"
        skill_tools = [t.get("name") for t in (sk.get("tools") or []) if t.get("name")]
        tools.update(skill_tools)
        skills.append({"name": name, "tools": skill_tools, "trigger_hint": (sk.get("description") or "")[:200]})
    return {
        "orchestration_type": info.get("orchestration_type") or "unknown",
        "skills": skills[:50],
        "dialog_flow_nodes": [],
        "transfer_rules_summary": "",
        "tool_catalog": sorted(tools)[:100],
    }


def get_reconnects(mongo_uri: str, db_name: str, voice_id: str) -> int:
    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=15000)
    try:
        from bson import ObjectId
        doc = client[db_name].AssistantSession.find_one(
            {"_id": ObjectId(voice_id)},
            {"voice_session.reconnects": 1},
        )
        return ((doc or {}).get("voice_session") or {}).get("reconnects", 0) or 0
    except Exception:
        return 0
    finally:
        client.close()
