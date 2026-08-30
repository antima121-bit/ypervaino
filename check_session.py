"""One-command helper for manually testing verify_event_counts.py against
BotProbe: given a session UUID, prints the reconnect flag (predicts whether
an exact match is expected) plus our computed EVENTS SHOWN / ACTIVE TYPES /
SPAN, ready to eyeball against BotProbe's Trace Viewer for the same UUID.

Usage:
  python3 check_session.py <session-uuid>

Requires .env.mongo (MONGO_URI, MONGO_DB_NAME).
"""

import sys

from pymongo import MongoClient

from bson import ObjectId

from lookup_session import load_mongo_env, resolve_voice_id, is_reconnect_session
from verify_event_counts import verify_event_counts

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 check_session.py <session-uuid>")
        sys.exit(1)

    session_uuid = sys.argv[1]
    env = load_mongo_env()
    client = MongoClient(env["MONGO_URI"], serverSelectionTimeoutMS=15000)
    try:
        db = client[env["MONGO_DB_NAME"]]

        voice_id = resolve_voice_id(db, session_uuid)
        if voice_id is None:
            print(f"ERROR: No AssistantSession found for {session_uuid}")
            sys.exit(1)

        tenant = (db.AssistantSession.find_one({"_id": ObjectId(voice_id)}, {"tenant": 1}) or {}).get("tenant")
        is_reconnect = is_reconnect_session(db, voice_id)

        result = verify_event_counts(db, session_uuid, botprobe_types=True, dedup=True)
    finally:
        client.close()

    if "error" in result:
        print("ERROR:", result["error"])
        sys.exit(1)

    print(f"session_uuid : {session_uuid}")
    print(f"tenant       : {tenant}")
    print(f"is_reconnect : {is_reconnect}", "(exact match expected)" if not is_reconnect else "(gap possible on EVENTS SHOWN -- known limitation)")
    print()
    print("Now load this same session_uuid in BotProbe and compare:")
    print()
    print(f"  EVENTS SHOWN : {result['events_shown']}")
    print(f"  ACTIVE TYPES : {result['active_types']}")
    print(f"  SPAN         : {result['span_minutes']}m")
