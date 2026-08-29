# Ypervaíno

A hackathon project that analyzes voice-bot conversations at scale — measuring the impact
of a backend change (model swap, guardrails, prompt change...) or discovering hidden
patterns in production traffic, without manually reading transcripts.

See [`hackthon.md`](./hackthon.md) for the full formal model this is built against.

## What's in here

This is a **lightweight, self-contained implementation** built for demo purposes:

- `server.py` — a zero-dependency Python backend (stdlib `http.server` + `sqlite3`).
  Seeds a small SQLite database shaped like [va-argus](https://gitlab.com/the-level-engineering/va-argus)'s
  Sessions data (sessions / turns / tool calls) with synthetic "before/after" conversations,
  computes real Primitives/Aspects from it, and calls the Gemini API to do real LLM-driven
  exploration and hypothesis generation.
- `new_study.html`, `explore.html`, `dashboard.html`, `sessions.html` — the 4 pages of the flow.

**Important:** the underlying conversation data is synthetic (seeded), not real production
traffic — we don't yet have access to va-argus's real Mongo/Postgres. The engine (sampling,
statistics, LLM calls, hypothesis testing) is real; swap the data source once real credentials
are available.

## Running it

No installs needed beyond Python 3 (already on macOS):

```bash
cd ypervaino-live
cp .env.example .env   # then paste your own GEMINI_API_KEY into .env
python3 server.py
```

Open **http://localhost:8765/** in your browser.

Get a free Gemini API key (no credit card needed) at **aistudio.google.com/apikey**.

## Flow

1. **New Study** (`/`) — describe what changed (or leave blank for Pure Discovery mode), set sample size / min support / significance level
2. **Explore & Approve** (`/explore`) — Gemini reads a sample of real transcripts, proposes aspects + hypotheses (each with a structured predicate), which are then tested against *all* seeded sessions for real match rates and significance
3. **Results** (`/results`) — before/after health distribution, aspect deltas, computed live from SQLite
4. **Sessions** (`/sessions`) — browse every seeded conversation, click one to see its full transcript + tool calls

## Known gaps (see `hackthon.md` for the full model)

- No real ScopeFilter (tenant/assistant/date range don't actually filter data yet)
- No real embedding-based clustering for exploration sampling (approximated with scenario/health stratification)
- Approving a plan on `/explore` doesn't yet feed back into what `/results` computes
- Not connected to real va-argus data (no Mongo/Postgres access yet)
