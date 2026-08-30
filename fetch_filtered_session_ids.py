"""Point 5: given the user inputs a study form would collect (input_schema.md
section 1.1 -- tenant, assistant, channel, date range(s), etc.), fetch the
matching session ids from MongoDB.

  ComparativeStudy   -> two lists: session_ids_before, session_ids_after
  SingleCohortStudy  -> one list:  session_ids

These ids are in the same form lookup_session.py expects as input (a
voice_session_id UUID for voice sessions; the AssistantSession _id directly
for chat sessions, since chat never populates voice_session_id -- see the
fallback in lookup_session.resolve_voice_id).

Usage:
  # Single cohort
  python3 fetch_filtered_session_ids.py \
      --study_type single_cohort \
      --tenant resound --assistant_origin_id <uuid> --channel voice \
      --date_range_start 2026-08-20T00:00:00 --date_range_end 2026-08-23T23:59:59

  # Comparative
  python3 fetch_filtered_session_ids.py \
      --study_type comparative \
      --tenant resound --assistant_origin_id <uuid> --channel voice \
      --date_range_before_start 2026-08-20T00:00:00 --date_range_before_end 2026-08-21T23:59:59 \
      --date_range_after_start  2026-08-22T00:00:00 --date_range_after_end  2026-08-23T23:59:59

Requires .env.mongo with MONGO_URI and MONGO_DB_NAME (gitignored -- never commit it).

NOT implemented here (kept simple per Dwijesh's ask -- see draft3/input_schema
for the full spec): `cohort_filters` / `conversation_predicate` compilation,
`traffic_split`, and stratified `n_eval` subsampling. `--limit` below is a
plain cap, not the stratified sample draft3 Phase 0 describes.
"""

import argparse
import sys
from datetime import datetime

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


SAFETY_MAX_TIME_MS = 10_000  # abort rather than let a bad query plan hammer production


def fetch_session_ids(db, tenant: str, assistant_origin_id: str, channel: str,
                       start: datetime, end: datetime, assistant_id: str = None,
                       limit: int = None) -> list:
    """ScopeFilter match (input_schema.md sec 1.1) -> list of session ids,
    each directly usable as input to lookup_session.py.

    Query shape is deliberately (tenant, start_time) first -- that matches
    AssistantSession's `tenant_1_start_time_1_is_metrics_computed_1` index.
    There is NO index on `assistant_origin_id` alone or combined with tenant
    (only `assistant_id` has one) -- filtering assistant_origin_id straight
    up would force a collection scan on a multi-million-doc collection. So
    we narrow by the indexed (tenant, start_time) first; assistant_origin_id
    and the channel condition are applied as a residual filter on that
    already-narrow result set, not scanned independently.
    """
    query = {
        "tenant": tenant,
        "start_time": {"$gte": start, "$lte": end},
        "assistant_origin_id": assistant_origin_id,
    }
    if assistant_id:
        query["assistant_id"] = assistant_id

    if channel == "voice":
        query["voice_session_id"] = {"$ne": None}
    elif channel == "chat":
        query["voice_session_id"] = None
        query["$or"] = [
            {"external_chat_session": {"$ne": None}},
            {"chat_transport_provider": {"$ne": None}},
        ]
    else:
        raise ValueError(f"channel must be 'voice' or 'chat', got {channel!r}")

    cursor = db.AssistantSession.find(
        query, {"_id": 1, "voice_session_id": 1}
    ).max_time_ms(SAFETY_MAX_TIME_MS)
    if limit:
        cursor = cursor.limit(limit)

    return [d["voice_session_id"] or str(d["_id"]) for d in cursor]


def fetch_filtered_session_ids(mongo_uri: str, db_name: str, args: argparse.Namespace) -> dict:
    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=15000)
    try:
        db = client[db_name]
        common = dict(
            tenant=args.tenant,
            assistant_origin_id=args.assistant_origin_id,
            assistant_id=args.assistant_id,
            channel=args.channel,
            limit=args.limit,
        )

        if args.study_type == "comparative":
            before = fetch_session_ids(
                db, start=args.date_range_before_start, end=args.date_range_before_end, **common
            )
            after = fetch_session_ids(
                db, start=args.date_range_after_start, end=args.date_range_after_end, **common
            )
            return {"session_ids_before": before, "session_ids_after": after}

        ids = fetch_session_ids(db, start=args.date_range_start, end=args.date_range_end, **common)
        return {"session_ids": ids}
    finally:
        client.close()


def _parse_dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Fetch session ids matching a study's scope (input_schema.md sec 1.1).")
    p.add_argument("--study_type", choices=["comparative", "single_cohort"], required=True)
    p.add_argument("--tenant", required=True)
    p.add_argument("--assistant_origin_id", required=True)
    p.add_argument("--assistant_id", default=None)
    p.add_argument("--channel", choices=["voice", "chat"], default="voice")
    p.add_argument("--limit", type=int, default=None, help="Simple cap on results per cohort (not stratified n_eval sampling).")

    p.add_argument("--date_range_start", type=_parse_dt)
    p.add_argument("--date_range_end", type=_parse_dt)
    p.add_argument("--date_range_before_start", type=_parse_dt)
    p.add_argument("--date_range_before_end", type=_parse_dt)
    p.add_argument("--date_range_after_start", type=_parse_dt)
    p.add_argument("--date_range_after_end", type=_parse_dt)
    return p


def validate_args(args: argparse.Namespace) -> None:
    if args.study_type == "single_cohort":
        if not (args.date_range_start and args.date_range_end):
            sys.exit("single_cohort requires --date_range_start and --date_range_end")
    else:
        missing = [
            n for n in ("date_range_before_start", "date_range_before_end",
                        "date_range_after_start", "date_range_after_end")
            if not getattr(args, n)
        ]
        if missing:
            sys.exit(f"comparative requires: {', '.join('--' + m for m in missing)}")


if __name__ == "__main__":
    args = build_arg_parser().parse_args()
    validate_args(args)

    env = load_mongo_env()
    result = fetch_filtered_session_ids(env["MONGO_URI"], env["MONGO_DB_NAME"], args)

    if args.study_type == "comparative":
        print(f"before: {len(result['session_ids_before'])} session ids")
        print(f"after:  {len(result['session_ids_after'])} session ids")
    else:
        print(f"{len(result['session_ids'])} session ids")

    import json
    print(json.dumps(result, indent=2))
