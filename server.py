"""Ypervaíno live demo server.

Zero third-party dependencies (stdlib only) so it runs on plain
`python3 server.py`. Seeds a SQLite DB shaped like va-argus's Sessions data
(AssistantSession / VoiceTurnMetric / ToolCall) split into "before"/"after"
cohorts with real dialogue text, computes hackthon.md #17 Primitives/Aspects
for real, and calls Gemini to do real LLM-driven exploration + hypothesis
generation (hackthon.md Phase 1/2) on a sample of real transcripts.

Run:  python3 server.py
Then open http://localhost:8765/ in a real browser (not the claude.ai artifact
link -- that page is sandboxed and can never reach a localhost server).
"""

import json
import os
import random
import re
import sqlite3
import statistics
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

DB_PATH = os.path.join(os.path.dirname(__file__), "ypervaino.db")
ENV_PATH = os.path.join(os.path.dirname(__file__), ".env")
PORT = 8765
GEMINI_MODEL = "gemini-3.5-flash-lite"

TOOLS = ["check_order_status", "cancel_order", "track_package", "issue_refund"]

SCENARIOS = {
    "order_status": {
        "tool": "check_order_status",
        "opener": "Where's my order #{oid}?",
        "ok_reply": "Found it — order #{oid} is out for delivery, arriving today by 6pm.",
        "err_reply": "Let me check that for you... one moment, the lookup is taking longer than usual.",
        "recover_reply": "Sorry for the wait — order #{oid} is out for delivery, arriving today.",
    },
    "cancel_order": {
        "tool": "cancel_order",
        "opener": "I want to cancel order #{oid}.",
        "ok_reply": "Done — order #{oid} has been cancelled and you'll get a refund in 3-5 days.",
        "err_reply": "Trying to cancel that now... give me a second.",
        "recover_reply": "Got it processed — order #{oid} is cancelled.",
    },
    "track_package": {
        "tool": "track_package",
        "opener": "Can you track my package please?",
        "ok_reply": "Your package is at the local depot and should arrive tomorrow.",
        "err_reply": "Hmm, the tracking system isn't responding right away, retrying...",
        "recover_reply": "Okay, found it — it's at the local depot, arriving tomorrow.",
    },
    "transfer": {
        "tool": None,
        "opener": "I need to talk to a real person right now.",
        "ok_reply": "Of course, transferring you to an agent now.",
        "err_reply": "I understand — let me see if I can help first. Can you tell me more about the issue?",
        "recover_reply": "Okay, connecting you to an agent now.",
    },
}

# Static VA Blueprint for the synthetic assistant (hackthon.md #2.5 / #17.4) --
# in a real deployment this would be fetched from va-argus's blueprint cache
# (blueprint_cache.json) or its live fetch path. Passed to the LLM as context
# so it can judge deviation from configured intent, not just raw transcript text.
VA_BLUEPRINT = {
    "assistant_name": "Resound Support Voice Agent",
    "orchestration_type": "single-agent, tool-calling",
    "skills": ["order_status", "cancel_order", "track_package", "transfer_to_agent"],
    "tools": [
        {"name": "check_order_status", "purpose": "Look up delivery ETA for an order ID"},
        {"name": "cancel_order", "purpose": "Cancel an order and trigger a refund"},
        {"name": "track_package", "purpose": "Look up carrier tracking status"},
        {"name": "issue_refund", "purpose": "Issue a refund without cancelling"},
    ],
    "instructions_summary": (
        "Resolve order/tracking/cancellation requests using tools before offering a human transfer. "
        "Transfer immediately if the user explicitly asks for a human."
    ),
}


def seed_if_empty(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM sessions")
    if cur.fetchone()[0] > 0:
        return

    rng = random.Random(42)
    scenario_keys = list(SCENARIOS.keys())

    def make_cohort(cohort: str, n: int, latency_mean: float, error_rate: float, red_rate: float, yellow_rate: float):
        for i in range(n):
            session_id = f"{cohort}-{i:04d}"
            scenario_key = rng.choice(scenario_keys)
            scenario = SCENARIOS[scenario_key]
            order_id = rng.randint(1000, 9999)
            hit_error = rng.random() < error_rate

            turns = [("user", scenario["opener"].format(oid=order_id))]
            if hit_error:
                turns.append(("assistant", scenario["err_reply"].format(oid=order_id)))
                turns.append(("user", "Okay, still there?"))
                turns.append(("assistant", scenario["recover_reply"].format(oid=order_id)))
            else:
                turns.append(("assistant", scenario["ok_reply"].format(oid=order_id)))
            extra_turns = rng.randint(0, 4)
            for _ in range(extra_turns):
                turns.append(("user", rng.choice([
                    "Thanks, one more question.", "Can you also check my account?", "Alright, thank you.",
                ])))
                turns.append(("assistant", "Sure, happy to help with that too."))

            turn_count = len(turns)
            duration = turn_count * rng.uniform(8, 22)
            roll = rng.random()
            classification = "RED" if roll < red_rate else ("YELLOW" if roll < red_rate + yellow_rate else "GREEN")

            cur.execute(
                "INSERT INTO sessions (session_id, cohort, scenario, turn_count, duration_secs, classification) VALUES (?, ?, ?, ?, ?, ?)",
                (session_id, cohort, scenario_key, turn_count, duration, classification),
            )
            for t, (speaker, text) in enumerate(turns):
                latency = max(80, rng.gauss(latency_mean, latency_mean * 0.25))
                ttft = max(60, rng.gauss(latency_mean * 0.7, latency_mean * 0.2))
                interrupted = 1 if rng.random() < 0.08 else 0
                cur.execute(
                    "INSERT INTO turns (session_id, turn_index, speaker, text, e2e_latency, llm_ttft, interrupted) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (session_id, t, speaker, text, latency, ttft, interrupted),
                )
            if scenario["tool"]:
                for _ in range(rng.randint(1, 2)):
                    cur.execute(
                        "INSERT INTO tool_calls (session_id, tool_name, error) VALUES (?, ?, ?)",
                        (session_id, scenario["tool"], "timeout" if hit_error else None),
                    )

    make_cohort("before", 180, latency_mean=410, error_rate=0.031, red_rate=0.08, yellow_rate=0.21)
    make_cohort("after", 180, latency_mean=585, error_rate=0.078, red_rate=0.15, yellow_rate=0.27)
    conn.commit()


def init_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY, cohort TEXT NOT NULL, scenario TEXT NOT NULL,
            turn_count INTEGER NOT NULL, duration_secs REAL NOT NULL, classification TEXT NOT NULL
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS turns (
            session_id TEXT NOT NULL, turn_index INTEGER NOT NULL, speaker TEXT NOT NULL, text TEXT NOT NULL,
            e2e_latency REAL NOT NULL, llm_ttft REAL NOT NULL, interrupted INTEGER NOT NULL
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS tool_calls (
            session_id TEXT NOT NULL, tool_name TEXT NOT NULL, error TEXT
        )"""
    )
    seed_if_empty(conn)
    return conn


def p95(values):
    if not values:
        return 0.0
    values = sorted(values)
    return values[min(len(values) - 1, int(round(0.95 * (len(values) - 1))))]


def pct_delta(before, after):
    return 0.0 if before == 0 else (after - before) / before * 100.0


def compute_results(conn: sqlite3.Connection) -> dict:
    cur = conn.cursor()

    def cohort_stats(cohort: str) -> dict:
        cur.execute("SELECT turn_count, duration_secs, classification FROM sessions WHERE cohort = ?", (cohort,))
        rows = cur.fetchall()
        n = len(rows)
        classes = [r[2] for r in rows]
        cur.execute(
            "SELECT t.e2e_latency, t.llm_ttft FROM turns t JOIN sessions s ON s.session_id = t.session_id WHERE s.cohort = ?",
            (cohort,),
        )
        turn_rows = cur.fetchall()
        cur.execute(
            "SELECT tc.error FROM tool_calls tc JOIN sessions s ON s.session_id = tc.session_id WHERE s.cohort = ?",
            (cohort,),
        )
        tool_rows = cur.fetchall()
        tool_total = len(tool_rows)
        tool_errors = sum(1 for r in tool_rows if r[0] is not None)
        return {
            "n": n,
            "avg_turn_count": round(statistics.mean([r[0] for r in rows]), 1) if rows else 0,
            "avg_duration_secs": round(statistics.mean([r[1] for r in rows]), 1) if rows else 0,
            "green_pct": round(classes.count("GREEN") / n * 100, 1) if n else 0,
            "yellow_pct": round(classes.count("YELLOW") / n * 100, 1) if n else 0,
            "red_pct": round(classes.count("RED") / n * 100, 1) if n else 0,
            "e2e_latency_p95": round(p95([r[0] for r in turn_rows]), 0),
            "llm_ttft_p95": round(p95([r[1] for r in turn_rows]), 0),
            "tool_error_rate_pct": round((tool_errors / tool_total * 100) if tool_total else 0, 1),
        }

    before, after = cohort_stats("before"), cohort_stats("after")
    aspects = [
        {"name": "Speed — LLM TTFT p95", "before": f"{int(before['llm_ttft_p95'])}ms", "after": f"{int(after['llm_ttft_p95'])}ms",
         "delta_pct": round(pct_delta(before["llm_ttft_p95"], after["llm_ttft_p95"]), 1), "good_if": "down"},
        {"name": "Failures — tool error rate", "before": f"{before['tool_error_rate_pct']}%", "after": f"{after['tool_error_rate_pct']}%",
         "delta_pct": round(pct_delta(before["tool_error_rate_pct"], after["tool_error_rate_pct"]), 1), "good_if": "down"},
        {"name": "Conversation length", "before": f"{before['avg_turn_count']} turns", "after": f"{after['avg_turn_count']} turns",
         "delta_pct": round(pct_delta(before["avg_turn_count"], after["avg_turn_count"]), 1), "good_if": "down"},
    ]
    return {
        "cohort_sizes": {"before": before["n"], "after": after["n"], "total": before["n"] + after["n"]},
        "health": {
            "before": {"green": before["green_pct"], "yellow": before["yellow_pct"], "red": before["red_pct"]},
            "after": {"green": after["green_pct"], "yellow": after["yellow_pct"], "red": after["red_pct"]},
        },
        "aspects": aspects,
    }


def load_env() -> dict:
    values = {}
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                values[k.strip()] = v.strip()
    return values


def _diverse_pick(conn: sqlite3.Connection, cohort: str, n: int) -> list:
    """Approximates hackthon.md's clustering-based exploration sampling (Phase 1)
    without an embedding model: groups by (scenario, classification) -- our
    stand-in for opening_intent_class + health cluster -- and round-robins
    across groups so the sample spans distinct conversation types instead of
    being pure random."""
    cur = conn.cursor()
    where, params = ("cohort = ?", [cohort]) if cohort else ("1=1", [])
    cur.execute(f"SELECT session_id, scenario, classification FROM sessions WHERE {where} ORDER BY RANDOM()", params)
    rows = cur.fetchall()
    groups = {}
    for session_id, scenario, classification in rows:
        groups.setdefault((scenario, classification), []).append((session_id, scenario, classification))

    picked, group_keys, i = [], list(groups.keys()), 0
    while len(picked) < n and any(groups.values()):
        key = group_keys[i % len(group_keys)]
        if groups[key]:
            picked.append(groups[key].pop())
        i += 1
        if i > 10000:
            break
    return picked[:n]


def sample_conversations(conn: sqlite3.Connection, mode: str = "comparative", n_explore: int = 10) -> list:
    cur = conn.cursor()
    picked = []
    if mode == "discovery":
        picked = _diverse_pick(conn, "", n_explore)
    else:
        n_each = max(1, n_explore // 2)
        picked = [(*row, "before") for row in _diverse_pick(conn, "before", n_each)] + \
                 [(*row, "after") for row in _diverse_pick(conn, "after", n_each)]

    samples = []
    for row in picked:
        if mode == "discovery":
            session_id, scenario, classification = row
            cur.execute("SELECT cohort FROM sessions WHERE session_id = ?", (session_id,))
            cohort = cur.fetchone()[0]
        else:
            session_id, scenario, classification, cohort = row
        cur.execute("SELECT speaker, text FROM turns WHERE session_id = ? ORDER BY turn_index", (session_id,))
        turns = cur.fetchall()
        samples.append({
            "session_id": session_id, "cohort": cohort, "scenario": scenario,
            "classification": classification,
            "transcript": [{"speaker": s, "text": t} for s, t in turns],
        })
    return samples


def build_prompt(samples: list, description: str, mode: str = "comparative") -> str:
    lines = [
        "You are analyzing a sample of voice-bot conversations to plan an impact analysis.",
        "",
        "VA Blueprint (assistant's configured intent -- use this to judge whether behavior deviates from what it's designed to do):",
        json.dumps(VA_BLUEPRINT, indent=2),
        "",
    ]
    if mode == "discovery":
        lines.append("Mode: PURE DISCOVERY -- there is no before/after split and no known change. Find hidden patterns in this single pool of conversations.")
    else:
        lines.append(f'Mode: COMPARATIVE -- change being investigated: "{description}"' if description else "Mode: COMPARATIVE -- no change description given, just compare the two windows.")
    lines.append("")
    lines.append("Sample conversations (id, cohort, transcript):")
    for s in samples:
        cohort_label = s["cohort"] if s["cohort"] else "n/a (discovery pool)"
        lines.append(f"\n--- {s['session_id']} [{cohort_label}, health={s['classification']}] ---")
        for turn in s["transcript"]:
            lines.append(f"{turn['speaker']}: {turn['text']}")

    lines.append(
        """

Reply with ONLY a single JSON object (no markdown fences, no commentary) matching exactly this shape:
{
  "exploration_summary": "2-4 sentence narrative of what you observed comparing before vs after",
  "aspects": [ {"name": "short aspect name", "description": "one sentence"} ],
  "hypotheses": [
    {
      "title": "short title",
      "claim": "one sentence plain-English claim",
      "matched_session_ids": ["id1", "id2"],
      "predicate": {
        "scenario": "order_status | cancel_order | track_package | transfer | null",
        "classification": "RED | YELLOW | GREEN | null",
        "min_turn_count": "integer or null",
        "requires_tool_error": "true | false | null",
        "keyword": "a lowercase word/phrase that must literally appear in the transcript, or null"
      }
    }
  ]
}
Every hypothesis MUST include a "predicate" using ONLY the fields above (any subset, others null) so it can be
mechanically tested against the full dataset -- this is a structured filter over available session data, not free text.
Propose 3-5 aspects and 2-4 hypotheses, grounded only in what you actually see in the transcripts above."""
    )
    return "\n".join(lines)


def evaluate_predicate(conn: sqlite3.Connection, predicate: dict, mode: str = "comparative",
                        min_support: int = 30, significance_level: float = 0.05) -> dict:
    """Run a hypothesis's predicate for real against every seeded session.

    ComparativeStudy: compares before vs after (support_count, match_rate, p_value per
    hackthon.md #9.4 ProofSpec / cohort_comparison). SingleCohortStudy / discovery:
    metric is just match_rate against min_support, no comparison group to test against."""
    cur = conn.cursor()
    where, params = [], []
    if predicate.get("scenario"):
        where.append("s.scenario = ?")
        params.append(predicate["scenario"])
    if predicate.get("classification"):
        where.append("s.classification = ?")
        params.append(predicate["classification"])
    if predicate.get("min_turn_count") not in (None, ""):
        where.append("s.turn_count >= ?")
        params.append(int(predicate["min_turn_count"]))
    if predicate.get("requires_tool_error") is True:
        where.append("s.session_id IN (SELECT session_id FROM tool_calls WHERE error IS NOT NULL)")
    elif predicate.get("requires_tool_error") is False:
        where.append("s.session_id NOT IN (SELECT session_id FROM tool_calls WHERE error IS NOT NULL)")
    if predicate.get("keyword"):
        where.append("s.session_id IN (SELECT session_id FROM turns WHERE lower(text) LIKE ?)")
        params.append(f"%{predicate['keyword'].lower()}%")
    clause = ("AND " + " AND ".join(where)) if where else ""

    def counts(cohort_filter: str, cohort_params: list):
        cur.execute(f"SELECT COUNT(*) FROM sessions s WHERE {cohort_filter} {clause}", cohort_params + params)
        matched = cur.fetchone()[0]
        cur.execute(f"SELECT COUNT(*) FROM sessions s WHERE {cohort_filter}", cohort_params)
        n = cur.fetchone()[0]
        return matched, n

    if mode == "discovery":
        matched, n = counts("1=1", [])
        support = matched
        return {
            "support_count": matched,
            "match_rate": round(matched / n * 100, 1) if n else 0.0,
            "rejected": support < min_support,
            "min_support": min_support,
            "metric": "match_rate",
        }

    matched_before, n_before = counts("s.cohort = ?", ["before"])
    matched_after, n_after = counts("s.cohort = ?", ["after"])
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


def two_proportion_z_test(x1: int, n1: int, x2: int, n2: int) -> float:
    """Two-tailed p-value for a two-proportion z-test, using math.erf (no scipy needed)."""
    import math
    if n1 == 0 or n2 == 0:
        return 1.0
    p1, p2 = x1 / n1, x2 / n2
    p_pool = (x1 + x2) / (n1 + n2)
    se = math.sqrt(p_pool * (1 - p_pool) * (1 / n1 + 1 / n2))
    if se == 0:
        return 1.0
    z = (p2 - p1) / se
    return 2 * (1 - 0.5 * (1 + math.erf(abs(z) / math.sqrt(2))))


def call_gemini(prompt: str) -> dict:
    env = load_env()
    api_key = env.get("GEMINI_API_KEY", "")
    if not api_key:
        return {"error": "GEMINI_API_KEY not set in .env"}

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={api_key}"
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            data = json.loads(resp.read())
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        text = re.sub(r"^```(json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
        return json.loads(text)
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


def list_sessions(conn: sqlite3.Connection, cohort: str = "", classification: str = "", limit: int = 50, offset: int = 0) -> dict:
    cur = conn.cursor()
    where, params = [], []
    if cohort:
        where.append("cohort = ?")
        params.append(cohort)
    if classification:
        where.append("classification = ?")
        params.append(classification)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    cur.execute(f"SELECT COUNT(*) FROM sessions {clause}", params)
    total = cur.fetchone()[0]
    cur.execute(
        f"SELECT session_id, cohort, scenario, turn_count, duration_secs, classification FROM sessions {clause} "
        f"ORDER BY session_id LIMIT ? OFFSET ?",
        params + [limit, offset],
    )
    rows = cur.fetchall()
    return {
        "total": total,
        "sessions": [
            {"session_id": r[0], "cohort": r[1], "scenario": r[2], "turn_count": r[3], "duration_secs": round(r[4], 1), "classification": r[5]}
            for r in rows
        ],
    }


def get_session_detail(conn: sqlite3.Connection, session_id: str):
    cur = conn.cursor()
    cur.execute(
        "SELECT session_id, cohort, scenario, turn_count, duration_secs, classification FROM sessions WHERE session_id = ?",
        (session_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    cur.execute(
        "SELECT turn_index, speaker, text, e2e_latency, llm_ttft, interrupted FROM turns WHERE session_id = ? ORDER BY turn_index",
        (session_id,),
    )
    turns = [
        {"turn_index": t[0], "speaker": t[1], "text": t[2], "e2e_latency": round(t[3], 0), "llm_ttft": round(t[4], 0), "interrupted": bool(t[5])}
        for t in cur.fetchall()
    ]
    cur.execute("SELECT tool_name, error FROM tool_calls WHERE session_id = ?", (session_id,))
    tool_calls = [{"tool_name": t[0], "error": t[1]} for t in cur.fetchall()]
    return {
        "session_id": row[0], "cohort": row[1], "scenario": row[2], "turn_count": row[3],
        "duration_secs": round(row[4], 1), "classification": row[5],
        "turns": turns, "tool_calls": tool_calls,
    }


CONN = init_db()
DIR = os.path.dirname(__file__)
SESSION_ID_RE = re.compile(r"^/api/v1/sessions/([\w-]+)$")


class Handler(BaseHTTPRequestHandler):
    def _json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
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

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        session_match = SESSION_ID_RE.match(path)

        if path == "/api/v1/ypervaino/results":
            self._json(compute_results(CONN))
        elif path == "/api/v1/ypervaino/explore":
            description = qs.get("description", [""])[0]
            mode = qs.get("mode", ["comparative"])[0]
            n_explore = int(qs.get("n_explore", ["10"])[0])
            min_support = int(qs.get("min_support", ["30"])[0])
            significance_level = float(qs.get("significance_level", ["0.05"])[0])
            samples = sample_conversations(CONN, mode=mode, n_explore=n_explore)
            prompt = build_prompt(samples, description, mode=mode)
            llm_out = call_gemini(prompt)
            if "hypotheses" in llm_out:
                for h in llm_out["hypotheses"]:
                    predicate = h.get("predicate") or {}
                    h["result"] = evaluate_predicate(CONN, predicate, mode=mode, min_support=min_support, significance_level=significance_level)
            self._json({"samples": samples, "llm": llm_out, "mode": mode})
        elif path == "/api/v1/sessions":
            self._json(list_sessions(
                CONN,
                cohort=qs.get("cohort", [""])[0],
                classification=qs.get("classification", [""])[0],
                limit=int(qs.get("limit", ["50"])[0]),
                offset=int(qs.get("offset", ["0"])[0]),
            ))
        elif session_match:
            detail = get_session_detail(CONN, session_match.group(1))
            if detail is None:
                self._json({"error": "not found"}, status=404)
            else:
                self._json(detail)
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

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    print(f"Ypervaíno live demo running at http://localhost:{PORT}/")
    ThreadingHTTPServer(("localhost", PORT), Handler).serve_forever()
