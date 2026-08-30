"""Automates the manual BotProbe -> MongoDB lookup chain Dwijesh flagged
("Mongo thing figure out"):

  Production call -> Conversation/Session ID (UUID, e.g. from Level AI/BotProbe)
    -> [was: manually paste into BotProbe, copy the "VOICE" id it shows,
         manually paste that into MongoDB Compass search]
    -> now: one function call, no BotProbe UI step needed.

How the two ids relate (reverse-engineered from a live lookup):
  BotProbe's "Session ID" input field  == AssistantSession.voice_session_id
  BotProbe's "VOICE -> ..." output     == AssistantSession._id (ObjectId)
                                        == SessionRequest.session_id

Usage:
  python3 lookup_session.py <botprobe-session-uuid>

Requires .env.mongo with MONGO_URI and MONGO_DB_NAME (gitignored -- never commit it).
"""

import sys
from pymongo import MongoClient


def load_mongo_env(path: str = ".env.mongo") -> dict:
    env = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def resolve_voice_id(db, session_uuid: str):
    """BotProbe 'Session ID' (UUID) -> internal voice/Mongo id (hex).

    Voice-channel sessions store this UUID in `voice_session_id`. Chat-channel
    sessions never populate that field, so `fetch_filtered_session_ids.py`
    hands back the AssistantSession `_id` directly for chat -- fall back to
    treating the input as that `_id` when the voice_session_id lookup misses.
    """
    doc = db.AssistantSession.find_one(
        {"voice_session_id": session_uuid}, {"_id": 1}
    )
    if doc:
        return str(doc["_id"])

    try:
        from bson import ObjectId
        if db.AssistantSession.find_one({"_id": ObjectId(session_uuid)}, {"_id": 1}):
            return session_uuid
    except Exception:
        pass
    return None


def get_session_requests(db, voice_id: str) -> list:
    """All SessionRequest turns for a resolved voice id, time-ordered."""
    return list(db.SessionRequest.find({"session_id": voice_id}).sort("created_at", 1))


def is_reconnect_session(db, voice_id: str) -> bool:
    """True if the call reconnected mid-session (voice_session.reconnects >= 1).
    Dwijesh's ask: surface this so reconnect samples can be filtered out of a
    study later if they turn out to cause issues (see MONGO_LOOKUP.md /
    verify_event_counts.py -- reconnect calls sometimes undercount events
    vs BotProbe)."""
    from bson import ObjectId
    try:
        doc = db.AssistantSession.find_one({"_id": ObjectId(voice_id)}, {"voice_session.reconnects": 1})
    except Exception:
        return False
    reconnects = ((doc or {}).get("voice_session") or {}).get("reconnects", 0) or 0
    return reconnects >= 1


def get_session_transcript(mongo_uri: str, db_name: str, botprobe_session_uuid: str) -> dict:
    """One-call convenience wrapper: UUID in, transcript out."""
    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=15000)
    try:
        db = client[db_name]
        voice_id = resolve_voice_id(db, botprobe_session_uuid)
        if voice_id is None:
            return {"error": f"No AssistantSession found with voice_session_id={botprobe_session_uuid}"}
        requests = get_session_requests(db, voice_id)
        return {
            "botprobe_session_uuid": botprobe_session_uuid,
            "voice_id": voice_id,
            "is_reconnect": is_reconnect_session(db, voice_id),
            "turn_count": len(requests),
            "turns": [
                {
                    "query": r.get("query"),
                    "final_response": r.get("final_response"),
                    "agent_name": r.get("agent_name"),
                    "tool_call_list": r.get("tool_call_list"),
                    "created_at": r.get("created_at"),
                }
                for r in requests
            ],
        }
    finally:
        client.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 lookup_session.py <botprobe-session-uuid>")
        sys.exit(1)

    env = load_mongo_env()
    result = get_session_transcript(env["MONGO_URI"], env["MONGO_DB_NAME"], sys.argv[1])

    if "error" in result:
        print("ERROR:", result["error"])
        sys.exit(1)

    print(f"voice_id: {result['voice_id']}  ({result['turn_count']} turns)\n")
    for t in result["turns"]:
        if t["query"]:
            print(f"User [{t['agent_name']}]: {t['query']}")
        print(f"Bot  [{t['agent_name']}]: {t['final_response']}")
        if t["tool_call_list"]:
            print(f"  tools: {t['tool_call_list']}")
        print()
