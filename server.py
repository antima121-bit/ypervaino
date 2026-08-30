"""Ypervaino live server -- now backed by real production data (bot_prod)
instead of synthetic SQLite. Built on fetch_filtered_session_ids.py,
lookup_session.py, and mongo_backend.py.

Run:  python3 server.py
Then open http://localhost:8765/ in a real browser (not the claude.ai artifact
link -- that page is sandboxed and can never reach a localhost server).

Requires .env.mongo (MONGO_URI, MONGO_DB_NAME) and .env (ANTHROPIC_API_KEY).
"""

import json
import math
import os
import re
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from fetch_filtered_session_ids import fetch_filtered_session_ids, load_mongo_env
from lookup_session import get_session_transcript, resolve_voice_id
from mongo_backend import get_client, list_tenants, compute_cohort_aspects, sample_real_transcripts, resolve_voice_ids_batch

PORT = 8765
ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"
DIR = os.path.dirname(__file__)
ENV_PATH = os.path.join(DIR, ".env")


class Args:
    """Mimics argparse.Namespace so we can reuse fetch_filtered_session_ids() as-is."""
    def __init__(self, **kw):
        self.__dict__.update(kw)


def parse_dt(s):
    return datetime.fromisoformat(s) if s else None


def load_env(path=ENV_PATH) -> dict:
    values = {}
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    values[k.strip()] = v.strip()
    return values


def two_proportion_z_test(x1, n1, x2, n2) -> float:
    if n1 == 0 or n2 == 0:
        return 1.0
    p1, p2 = x1 / n1, x2 / n2
    p_pool = (x1 + x2) / (n1 + n2)
    se = math.sqrt(p_pool * (1 - p_pool) * (1 / n1 + 1 / n2))
    if se == 0:
        return 1.0
    z = (p2 - p1) / se
    return 2 * (1 - 0.5 * (1 + math.erf(abs(z) / math.sqrt(2))))


def pct_delta(before, after):
    return 0.0 if before == 0 else (after - before) / before * 100.0


# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------

def build_prompt(samples: list, description: str, mode: str) -> str:
    lines = [
        "You are analyzing a sample of real voice-bot conversations (from production) to plan an impact analysis.",
        "Mode: PURE DISCOVERY -- find hidden patterns in this pool of conversations." if mode == "discovery"
        else (f'Mode: COMPARATIVE -- change being investigated: "{description}"' if description
              else "Mode: COMPARATIVE -- no change description given, just compare the two windows."),
        "",
        "Sample conversations (id, transcript):",
    ]
    for s in samples:
        lines.append(f"\n--- {s['session_id']} ---")
        for turn in s["transcript"]:
            lines.append(f"{turn['speaker']}: {turn['text']}")

    lines.append(
        """

Reply with ONLY a single JSON object (no markdown fences, no commentary) matching exactly this shape:
{
  "exploration_summary": "2-4 sentence narrative of what you observed",
  "aspects": [ {"name": "short aspect name", "description": "one sentence"} ],
  "suggested_plots": [ {"title": "short plot title", "description": "one sentence on what it would show"} ],
  "suggested_tables": [ {"title": "short table title", "description": "one sentence on what it would show"} ],
  "hypotheses": [
    {
      "title": "short title",
      "claim": "one sentence plain-English claim",
      "matched_session_ids": ["id1", "id2"],
      "predicate": {
        "min_turn_count": "integer or null",
        "requires_tool_error": "true | false | null",
        "keyword": "a lowercase word/phrase that must literally appear in a user query, or null"
      }
    }
  ]
}
Every hypothesis MUST include a "predicate" using ONLY the fields above (any subset, others null) --
these are the only fields we can mechanically test against the full dataset. Do not invent other
predicate fields (no "scenario", no "classification" -- those don't exist in this data).
Propose 3-5 aspects, 1-3 suggested plots, 1-2 suggested tables, and 2-4 hypotheses, grounded only
in what you actually see above."""
    )
    return "\n".join(lines)


def call_llm(prompt: str) -> dict:
    env = load_env()
    api_key = env.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return {"error": "ANTHROPIC_API_KEY not set in .env"}

    url = "https://api.anthropic.com/v1/messages"
    body = json.dumps({
        "model": ANTHROPIC_MODEL,
        "max_tokens": 2000,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request(
        url, data=body,
        headers={
            "content-type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            data = json.loads(resp.read())
        text = data["content"][0]["text"]
        text = re.sub(r"^```(json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
        return json.loads(text)
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


# ---------------------------------------------------------------------------
# Predicate evaluation over real session_ids (Phase 3 hypothesis testing)
# ---------------------------------------------------------------------------

def fetch_session_features(db, session_ids: list) -> dict:
    if not session_ids:
        return {}
    pipeline = [
        {"$match": {"session_id": {"$in": session_ids}}},
        {"$group": {
            "_id": "$session_id",
            "turn_count": {"$sum": {"$cond": [{"$eq": ["$event_type", "USER_QUERY"]}, 1, 0]}},
            "has_tool_error": {"$max": {"$cond": [
                {"$and": [
                    {"$eq": ["$event_type", "TOOL_CALL_RESULT"]},
                    {"$ne": [{"$ifNull": ["$event_value.error", None]}, None]},
                ]}, 1, 0,
            ]}},
            "queries": {"$push": {"$cond": [{"$eq": ["$event_type", "USER_QUERY"]}, "$content", "$$REMOVE"]}},
        }},
    ]
    rows = db.AssistantEvent.aggregate(pipeline, maxTimeMS=15000)
    return {r["_id"]: r for r in rows}


def evaluate_predicate(db, predicate: dict, mode: str, ids_before: list, ids_after: list,
                        min_support: int, significance_level: float) -> dict:
    all_ids = list(ids_before) + list(ids_after)
    features = fetch_session_features(db, all_ids)

    def matches(sid):
        f = features.get(sid)
        if not f:
            return False
        if predicate.get("min_turn_count") not in (None, "") and f["turn_count"] < int(predicate["min_turn_count"]):
            return False
        if predicate.get("requires_tool_error") is True and not f["has_tool_error"]:
            return False
        if predicate.get("requires_tool_error") is False and f["has_tool_error"]:
            return False
        kw = predicate.get("keyword")
        if kw and not any(kw.lower() in (q or "").lower() for q in f.get("queries", [])):
            return False
        return True

    if mode == "discovery":
        matched = sum(1 for sid in ids_before if matches(sid))  # discovery uses the single pool as "before"
        n = len(ids_before)
        return {
            "support_count": matched,
            "match_rate": round(matched / n * 100, 1) if n else 0.0,
            "rejected": matched < min_support,
            "min_support": min_support,
            "metric": "match_rate",
        }

    matched_before = sum(1 for sid in ids_before if matches(sid))
    matched_after = sum(1 for sid in ids_after if matches(sid))
    n_before, n_after = len(ids_before), len(ids_after)
    p_value = two_proportion_z_test(matched_before, n_before, matched_after, n_after)
    total_support = matched_before + matched_after
    return {
        "support_before": matched_before,
        "support_after": matched_after,
        "rate_before": round(matched_before / n_before * 100, 1) if n_before else 0.0,
        "rate_after": round(matched_after / n_after * 100, 1) if n_after else 0.0,
        "p_value": round(p_value, 4),
        "significant": bool(p_value < significance_level and total_support >= min_support),
        "rejected": total_support < min_support,
        "min_support": min_support,
        "metric": "cohort_delta",
    }


def compute_results(db, ids_before: list, ids_after: list) -> dict:
    before = compute_cohort_aspects(db, ids_before)
    after = compute_cohort_aspects(db, ids_after)
    aspects = [
        {"name": "Conversation length", "before": f"{before['avg_turn_count']} turns", "after": f"{after['avg_turn_count']} turns",
         "delta_pct": round(pct_delta(before["avg_turn_count"], after["avg_turn_count"]), 1), "good_if": "down"},
        {"name": "Session duration", "before": f"{before['avg_duration_secs']}s", "after": f"{after['avg_duration_secs']}s",
         "delta_pct": round(pct_delta(before["avg_duration_secs"], after["avg_duration_secs"]), 1), "good_if": "down"},
        {"name": "Tool error rate", "before": f"{before['tool_error_rate_pct']}%", "after": f"{after['tool_error_rate_pct']}%",
         "delta_pct": round(pct_delta(before["tool_error_rate_pct"], after["tool_error_rate_pct"]), 1), "good_if": "down"},
        {"name": "Avg tool latency", "before": f"{int(before['avg_tool_latency_ms'])}ms", "after": f"{int(after['avg_tool_latency_ms'])}ms",
         "delta_pct": round(pct_delta(before["avg_tool_latency_ms"], after["avg_tool_latency_ms"]), 1), "good_if": "down"},
    ]
    return {
        "cohort_sizes": {"before": before["n"], "after": after["n"], "total": before["n"] + after["n"]},
        "aspects": aspects,
    }


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    def _json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _html(self, filename: str) -> None:
        with open(os.path.join(DIR, filename), "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _make_args(self, qs) -> Args:
        g = lambda k, d=None: qs.get(k, [d])[0]
        return Args(
            study_type=g("study_type", "single_cohort"),
            tenant=g("tenant"),
            assistant_origin_id=g("assistant_origin_id"),
            assistant_id=g("assistant_id") or None,
            channel=g("channel", "voice"),
            limit=int(g("limit", "50")),
            date_range_start=parse_dt(g("date_range_start")),
            date_range_end=parse_dt(g("date_range_end")),
            date_range_before_start=parse_dt(g("date_range_before_start")),
            date_range_before_end=parse_dt(g("date_range_before_end")),
            date_range_after_start=parse_dt(g("date_range_after_start")),
            date_range_after_end=parse_dt(g("date_range_after_end")),
        )

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path, qs = parsed.path, parse_qs(parsed.query)

        try:
            if path == "/api/v1/ypervaino/tenants":
                client, db_name = get_client()
                try:
                    self._json({"tenants": list_tenants(client[db_name])})
                finally:
                    client.close()

            elif path == "/api/v1/ypervaino/session_ids":
                args = self._make_args(qs)
                mongo_env = load_mongo_env()
                result = fetch_filtered_session_ids(mongo_env["MONGO_URI"], mongo_env["MONGO_DB_NAME"], args)
                self._json(result)

            elif path == "/api/v1/ypervaino/explore":
                description = qs.get("description", [""])[0]
                mode = qs.get("mode", ["comparative"])[0]
                n_explore = int(qs.get("n_explore", ["10"])[0])
                min_support = int(qs.get("min_support", ["30"])[0])
                significance_level = float(qs.get("significance_level", ["0.05"])[0])
                args = self._make_args(qs)
                args.study_type = "single_cohort" if mode == "discovery" else "comparative"

                mongo_env = load_mongo_env()
                ids_result = fetch_filtered_session_ids(mongo_env["MONGO_URI"], mongo_env["MONGO_DB_NAME"], args)
                ids_before = ids_result.get("session_ids") or ids_result.get("session_ids_before", [])
                ids_after = ids_result.get("session_ids_after", [])

                client, db_name = get_client()
                try:
                    db = client[db_name]
                    n_each = max(1, n_explore // 2) if mode != "discovery" else n_explore
                    samples = sample_real_transcripts(db, ids_before, n_each)
                    if mode != "discovery":
                        samples += sample_real_transcripts(db, ids_after, n_each)

                    if not samples:
                        self._json({"samples": [], "llm": {"error": "No matching sessions found for this scope/date range."}, "mode": mode})
                        return

                    prompt = build_prompt(samples, description, mode)
                    llm_out = call_llm(prompt)
                    # Deliberately no hypothesis-predicate evaluation here -- Explore is a
                    # read-only plan display (draft3.md sec 2, UI_design.md sec 2.3). Numbers
                    # only appear on Results, after Execute.
                    self._json({"samples": samples, "llm": llm_out, "mode": mode,
                                "cohort_sizes": {"before": len(ids_before), "after": len(ids_after)}})
                finally:
                    client.close()

            elif path == "/api/v1/ypervaino/results":
                args = self._make_args(qs)
                mongo_env = load_mongo_env()
                ids_result = fetch_filtered_session_ids(mongo_env["MONGO_URI"], mongo_env["MONGO_DB_NAME"], args)
                ids_before = ids_result.get("session_ids") or ids_result.get("session_ids_before", [])
                ids_after = ids_result.get("session_ids_after", [])

                client, db_name = get_client()
                try:
                    db = client[db_name]
                    self._json(compute_results(
                        db, resolve_voice_ids_batch(db, ids_before), resolve_voice_ids_batch(db, ids_after)
                    ))
                finally:
                    client.close()

            elif path == "/api/v1/ypervaino/session_detail":
                session_uuid = qs.get("session_id", [""])[0]
                mongo_env = load_mongo_env()
                result = get_session_transcript(mongo_env["MONGO_URI"], mongo_env["MONGO_DB_NAME"], session_uuid)
                self._json(result, status=404 if "error" in result else 200)

            elif path in ("/", "/index.html", "/new-study"):
                self._html("new_study.html")
            elif path == "/explore":
                self._html("explore.html")
            elif path == "/results":
                self._html("dashboard.html")
            elif path == "/sessions":
                self._html("sessions.html")
            else:
                self.send_response(404)
                self.end_headers()
        except Exception as e:
            self._json({"error": f"{type(e).__name__}: {e}"}, status=500)

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    print(f"Ypervaino live server (real data) running at http://localhost:{PORT}/")
    ThreadingHTTPServer(("localhost", PORT), Handler).serve_forever()
