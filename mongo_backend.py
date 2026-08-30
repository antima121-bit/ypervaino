"""Real-data backend for the Ypervaino dashboard (server.py), replacing the
synthetic SQLite demo data with live queries against bot_prod, built on top
of fetch_filtered_session_ids.py and lookup_session.py.

Aspects computed here are deliberately limited to what's directly verified
against real AssistantEvent documents (see MONGO_LOOKUP.md):
  - turn_count       : count of USER_QUERY events
  - duration_secs    : last event timestamp - first event timestamp
  - tool_invocations : count of TOOL_CALL_RESULT events
  - tool_error_rate  : % of TOOL_CALL_RESULT events with a non-null event_value.error
                        (best-effort heuristic -- we could not find a real failing
                        tool call to confirm this field name without an unscoped,
                        unsafe query; flag this to Dwijesh before trusting it)
  - avg_tool_latency : mean of event_value.latency across TOOL_CALL_RESULT events

No RED/YELLOW/GREEN health classification -- that was va-argus's own derived
signal engine, which we don't have here. Do not invent one without agreement.
"""

from pymongo import MongoClient

from fetch_filtered_session_ids import load_mongo_env
from lookup_session import resolve_voice_id, get_session_requests

SAFETY_MAX_TIME_MS = 15_000


def get_client():
    env = load_mongo_env()
    return MongoClient(env["MONGO_URI"], serverSelectionTimeoutMS=15000), env["MONGO_DB_NAME"]


def list_tenants(db, limit: int = 200) -> list:
    """Distinct tenants -- `tenant` has its own index so this is safe."""
    names = db.AssistantSession.distinct("tenant")
    return sorted(n for n in names if n and n != "None")[:limit]


def resolve_voice_ids_batch(db, session_ids: list) -> list:
    """AssistantEvent.session_id stores the resolved voice/Mongo id (hex), not
    the UUID fetch_filtered_session_ids hands back -- batch-resolve via one
    indexed $in query before querying AssistantEvent. Falls back to passing
    an id through unresolved (chat-channel ids are already the resolved form,
    same as lookup_session.resolve_voice_id's fallback)."""
    if not session_ids:
        return []
    docs = db.AssistantSession.find(
        {"voice_session_id": {"$in": session_ids}}, {"_id": 1, "voice_session_id": 1}
    )
    resolved = {d["voice_session_id"]: str(d["_id"]) for d in docs}
    return [resolved.get(sid, sid) for sid in session_ids]


def compute_cohort_aspects(db, session_ids: list) -> dict:
    """One aggregation call over AssistantEvent for every id in session_ids
    (session_id is indexed, so $in here is efficient) -> per-cohort averages."""
    if not session_ids:
        return {"n": 0, "avg_turn_count": 0, "avg_duration_secs": 0,
                "avg_tool_invocations": 0, "tool_error_rate_pct": 0, "avg_tool_latency_ms": 0}

    pipeline = [
        {"$match": {"session_id": {"$in": session_ids}}},
        {"$group": {
            "_id": "$session_id",
            "first_ts": {"$min": "$timestamp"},
            "last_ts": {"$max": "$timestamp"},
            "turn_count": {"$sum": {"$cond": [{"$eq": ["$event_type", "USER_QUERY"]}, 1, 0]}},
            "tool_count": {"$sum": {"$cond": [{"$eq": ["$event_type", "TOOL_CALL_RESULT"]}, 1, 0]}},
            "tool_error_count": {"$sum": {"$cond": [
                {"$and": [
                    {"$eq": ["$event_type", "TOOL_CALL_RESULT"]},
                    {"$ne": [{"$ifNull": ["$event_value.error", None]}, None]},
                ]}, 1, 0,
            ]}},
            "tool_latency_sum": {"$sum": {"$cond": [
                {"$eq": ["$event_type", "TOOL_CALL_RESULT"]},
                {"$ifNull": ["$event_value.latency", 0]}, 0,
            ]}},
        }},
    ]
    rows = list(db.AssistantEvent.aggregate(pipeline, maxTimeMS=SAFETY_MAX_TIME_MS))
    if not rows:
        return {"n": 0, "avg_turn_count": 0, "avg_duration_secs": 0,
                "avg_tool_invocations": 0, "tool_error_rate_pct": 0, "avg_tool_latency_ms": 0}

    n = len(rows)
    total_tool_count = sum(r["tool_count"] for r in rows)
    total_tool_errors = sum(r["tool_error_count"] for r in rows)
    total_tool_latency = sum(r["tool_latency_sum"] for r in rows)

    return {
        "n": n,
        "avg_turn_count": round(sum(r["turn_count"] for r in rows) / n, 1),
        "avg_duration_secs": round(
            sum((r["last_ts"] - r["first_ts"]).total_seconds() for r in rows) / n, 1
        ),
        "avg_tool_invocations": round(total_tool_count / n, 2),
        "tool_error_rate_pct": round((total_tool_errors / total_tool_count * 100) if total_tool_count else 0, 1),
        "avg_tool_latency_ms": round((total_tool_latency / total_tool_count) if total_tool_count else 0, 0),
    }


def sample_real_transcripts(db, session_ids: list, n: int) -> list:
    """Pull full transcripts for up to n ids -- used as the LLM exploration
    sample. Reuses the single already-open `db` connection for every id
    (previously each id opened its own MongoClient via get_session_transcript
    -- a fresh TLS handshake + auth per session, ~4s each against Atlas --
    this is why Explore used to take so long)."""
    samples = []
    for sid in session_ids[:n]:
        voice_id = resolve_voice_id(db, sid)
        if voice_id is None:
            continue
        requests = get_session_requests(db, voice_id)
        samples.append({
            "session_id": sid,
            "transcript": [
                {"speaker": "user" if r.get("query") else "assistant", "text": r.get("query") or r.get("final_response")}
                for r in requests
            ],
        })
    return samples
