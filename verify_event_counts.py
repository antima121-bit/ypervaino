"""

Prints the same summary numbers BotProbe's Trace Viewer shows at the top
(EVENTS SHOWN / ACTIVE TYPES / SPAN), computed directly from AssistantEvent,
so you can eyeball them side-by-side against BotProbe for any session.

BACKGROUND -- two separate findings from real-session investigation:

1. BotProbe's "EVENTS SHOWN" is NOT a global dedup total -- it's the sum of
   only the event types checked in its left sidebar type-filter. We verified
   BotProbe's fixed default-active set is exactly these 12 types:
     CALL_TRANSFER_COMPLETED, CALL_TRANSFER_PAYLOAD, CALL_TRANSFER_REQUESTED,
     CONTEXTUAL_QUERY_GENERATED, DEBUG.SKILL_ROUTED, DEBUG.TOOL_INVOKED,
     RESPONSE.FINAL, SESSION_END, TOOL_CALL_ERROR, TOOL_CALL_RESULT,
     USER_QUERY, WEBSOCKET.CONNECTED
   Everything else (GUARDRAIL_CHECK, DEBUG.TOOL_ERROR, BACKEND_STATE_*,
   ACTIVE_TOOL_*, etc.) is excluded from BotProbe's default view entirely --
   this is a type filter, not deduplication.

2. Within that 12-type set, one real duplicate exists: SESSION_END fires
   twice on sessions where voice_session.reconnects >= 1 (verified 6/6 real
   sessions with a duplicate SESSION_END all had reconnects=1, and zero
   false positives found on sessions with reconnects=0) -- e.g. content
   "SESSION_END" then, ~1-5 minutes later, "Assistant Session Ended with
   Timeout". Both fire under the SAME session_id (confirmed -- no hidden
   second session), so this narrow fix (keep first SESSION_END, drop the
   rest) is safe: it only ever touches sessions that already have 2+
   SESSION_END rows, and never touches any other event type. This replaces
   the earlier generic (request_id, turn_id, event_type) dedup attempt,
   which was WRONG -- it also collapsed genuinely-distinct events (e.g. 8
   separate real DEBUG.SKILL_ROUTED routing decisions) that happen to share
   request_id=None/turn_id=None with the true SESSION_END duplicate.

   KNOWN OPEN GAP: on reconnect sessions specifically, BotProbe's own count
   for USER_QUERY/RESPONSE.FINAL/DEBUG.SKILL_ROUTED/DEBUG.TOOL_INVOKED runs
   *higher* than our raw AssistantEvent count for the same session_id (one
   verified example: +14/+4/+4/+1). All events are confirmed to live under
   one session_id/span already (not a second hidden session), so this isn't
   solved by dedup or by merging another id -- the extra events BotProbe
   counts aren't visible to us at all via AssistantEvent. Diagnosing this
   needs bot source access to the reconnect handler (kb_bot), which we don't
   have -- flag it as a known limitation for reconnect sessions rather than
   guessing further. Non-reconnect sessions are unaffected: every other
   type (TOOL_CALL_RESULT, CONTEXTUAL_QUERY_GENERATED, CALL_TRANSFER_*,
   TOOL_CALL_ERROR, WEBSOCKET.CONNECTED) matched BotProbe exactly with zero
   gap in the verified example.

Usage:
  python3 verify_event_counts.py <session-uuid>
  python3 verify_event_counts.py <session-uuid> --include-debug=false
  python3 verify_event_counts.py <session-uuid> --botprobe-types   # sum only BotProbe's 12 default-active types
  python3 verify_event_counts.py <session-uuid> --dedup            # also collapse duplicate SESSION_END (keep first)

Requires .env.mongo (MONGO_URI, MONGO_DB_NAME).
"""

import sys

from pymongo import MongoClient

from lookup_session import load_mongo_env, resolve_voice_id

# BotProbe's verified fixed default-active type filter (see docstring finding #1).
BOTPROBE_DEFAULT_TYPES = {
    "CALL_TRANSFER_COMPLETED", "CALL_TRANSFER_PAYLOAD", "CALL_TRANSFER_REQUESTED",
    "CONTEXTUAL_QUERY_GENERATED", "DEBUG.SKILL_ROUTED", "DEBUG.TOOL_INVOKED",
    "RESPONSE.FINAL", "SESSION_END", "TOOL_CALL_ERROR", "TOOL_CALL_RESULT",
    "USER_QUERY", "WEBSOCKET.CONNECTED",
}


def dedupe_events(events: list) -> list:
    """Verified narrow fix (see docstring finding #2): collapse duplicate
    SESSION_END rows, keep the first chronologically. Never touches any other
    event type -- safe because it only activates when 2+ SESSION_END rows
    already exist, which so far only happens on reconnect sessions."""
    seen_session_end = False
    kept = []
    for e in events:
        if e["event_type"] == "SESSION_END":
            if seen_session_end:
                continue
            seen_session_end = True
        kept.append(e)
    return kept


def verify_event_counts(
    db, session_uuid: str, include_debug: bool = True, dedup: bool = False, botprobe_types: bool = False
) -> dict:
    voice_id = resolve_voice_id(db, session_uuid)
    if voice_id is None:
        return {"error": f"No AssistantSession found for {session_uuid}"}

    query = {"session_id": voice_id}
    if not include_debug:
        query["is_debug_event"] = False

    events = list(
        db.AssistantEvent.find(query, {"event_type": 1, "timestamp": 1, "is_debug_event": 1, "request_id": 1, "turn_id": 1})
        .sort("timestamp", 1)
        .max_time_ms(10_000)
    )
    if not events:
        return {"error": f"No AssistantEvent rows for voice_id={voice_id} (session {session_uuid})"}

    raw_count = len(events)
    # Span always comes from the full raw timeline (BotProbe's SPAN reflects
    # true first/last event regardless of its type-filter or the SESSION_END
    # dedup -- verified: BotProbe showed 9.3m span while tallying SESSION_END
    # as 1, using the *later* SESSION_END's timestamp as the true session end).
    span_seconds = (events[-1]["timestamp"] - events[0]["timestamp"]).total_seconds()

    if botprobe_types:
        events = [e for e in events if e["event_type"] in BOTPROBE_DEFAULT_TYPES]
    if dedup:
        events = dedupe_events(events)

    type_counts = {}
    for e in events:
        type_counts[e["event_type"]] = type_counts.get(e["event_type"], 0) + 1

    debug_count = sum(1 for e in events if e.get("is_debug_event"))

    return {
        "session_uuid": session_uuid,
        "voice_id": voice_id,
        "events_shown": len(events),
        "raw_event_count": raw_count,
        "dedup_applied": dedup,
        "botprobe_types_applied": botprobe_types,
        "active_types": len(type_counts),
        "span_minutes": round(span_seconds / 60, 1),
        "debug_event_count": debug_count,
        "non_debug_event_count": len(events) - debug_count,
        "type_counts": dict(sorted(type_counts.items(), key=lambda kv: -kv[1])),
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 verify_event_counts.py <session-uuid> [--include-debug=false] [--botprobe-types] [--dedup]")
        sys.exit(1)

    args = sys.argv[2:]
    include_debug = "--include-debug=false" not in args
    dedup = "--dedup" in args
    botprobe_types = "--botprobe-types" in args

    env = load_mongo_env()
    client = MongoClient(env["MONGO_URI"], serverSelectionTimeoutMS=15000)
    try:
        db = client[env["MONGO_DB_NAME"]]
        result = verify_event_counts(db, sys.argv[1], include_debug=include_debug, dedup=dedup, botprobe_types=botprobe_types)
    finally:
        client.close()

    if "error" in result:
        print("ERROR:", result["error"])
        sys.exit(1)

    print(f"session_uuid : {result['session_uuid']}")
    print(f"voice_id     : {result['voice_id']}")
    print()
    if result["botprobe_types_applied"]:
        print(f"(filtered to BotProbe's 12 default-active types; raw was {result['raw_event_count']})")
    if result["dedup_applied"] and result["raw_event_count"] != result["events_shown"]:
        print(f"(SESSION_END deduped)")
    print(f"EVENTS SHOWN : {result['events_shown']}   <- compare against BotProbe's top bar")
    print(f"ACTIVE TYPES : {result['active_types']}   <- compare against BotProbe's top bar")
    print(f"SPAN         : {result['span_minutes']}m  <- compare against BotProbe's top bar")
    print()
    print(f"(of which: {result['debug_event_count']} debug events, {result['non_debug_event_count']} non-debug)")
    print()
    print("Event type breakdown:")
    for t, c in result["type_counts"].items():
        print(f"  {t}: {c}")
