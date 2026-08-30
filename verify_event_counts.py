"""Testing tool for Dwijesh's ask: "test point 4 and 5 on various clients/bots,
check if we are getting exactly equal number of events as in BotProbe."

Prints the same summary numbers BotProbe's Trace Viewer shows at the top
(EVENTS SHOWN / ACTIVE TYPES / SPAN), computed directly from AssistantEvent,
so you can eyeball them side-by-side against BotProbe for any session.

Usage:
  python3 verify_event_counts.py <session-uuid>
  python3 verify_event_counts.py <session-uuid> --include-debug=false

Requires .env.mongo (MONGO_URI, MONGO_DB_NAME).
"""

import sys
from datetime import timezone

from pymongo import MongoClient

from lookup_session import load_mongo_env, resolve_voice_id


def verify_event_counts(db, session_uuid: str, include_debug: bool = True) -> dict:
    voice_id = resolve_voice_id(db, session_uuid)
    if voice_id is None:
        return {"error": f"No AssistantSession found for {session_uuid}"}

    query = {"session_id": voice_id}
    if not include_debug:
        query["is_debug_event"] = False

    events = list(
        db.AssistantEvent.find(query, {"event_type": 1, "timestamp": 1, "is_debug_event": 1})
        .sort("timestamp", 1)
        .max_time_ms(10_000)
    )
    if not events:
        return {"error": f"No AssistantEvent rows for voice_id={voice_id} (session {session_uuid})"}

    type_counts = {}
    for e in events:
        type_counts[e["event_type"]] = type_counts.get(e["event_type"], 0) + 1

    span_seconds = (events[-1]["timestamp"] - events[0]["timestamp"]).total_seconds()
    debug_count = sum(1 for e in events if e.get("is_debug_event"))

    return {
        "session_uuid": session_uuid,
        "voice_id": voice_id,
        "events_shown": len(events),
        "active_types": len(type_counts),
        "span_minutes": round(span_seconds / 60, 1),
        "debug_event_count": debug_count,
        "non_debug_event_count": len(events) - debug_count,
        "type_counts": dict(sorted(type_counts.items(), key=lambda kv: -kv[1])),
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 verify_event_counts.py <session-uuid> [--include-debug=false]")
        sys.exit(1)

    include_debug = True
    if len(sys.argv) > 2 and sys.argv[2] == "--include-debug=false":
        include_debug = False

    env = load_mongo_env()
    client = MongoClient(env["MONGO_URI"], serverSelectionTimeoutMS=15000)
    try:
        db = client[env["MONGO_DB_NAME"]]
        result = verify_event_counts(db, sys.argv[1], include_debug=include_debug)
    finally:
        client.close()

    if "error" in result:
        print("ERROR:", result["error"])
        sys.exit(1)

    print(f"session_uuid : {result['session_uuid']}")
    print(f"voice_id     : {result['voice_id']}")
    print()
    print(f"EVENTS SHOWN : {result['events_shown']}   <- compare against BotProbe's top bar")
    print(f"ACTIVE TYPES : {result['active_types']}   <- compare against BotProbe's top bar")
    print(f"SPAN         : {result['span_minutes']}m  <- compare against BotProbe's top bar")
    print()
    print(f"(of which: {result['debug_event_count']} debug events, {result['non_debug_event_count']} non-debug)")
    print()
    print("Event type breakdown:")
    for t, c in result["type_counts"].items():
        print(f"  {t}: {c}")
