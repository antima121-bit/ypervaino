# Session discovery & event loading

**Solves:** how Ypervaíno gets from a scoped study (tenant, dates, assistant) to full
conversation event logs — without manually using BotProbe's UI or MongoDB Compass.

**v1 data split (confirmed 2026-08-30):**

| Step | Source | What |
|------|--------|------|
| Session discovery | **Mongo** `AssistantSession` | List/filter candidates; resolve UUID ↔ internal id |
| Event trace | **BotProbe `/trace` API** | Full ordered event log (Elasticsearch-backed) |

Mongo `AssistantEvent` holds only a **subset** of event types (kb_bot's
`MONGO_PERSISTED_EVENT_TYPES`). LLM/token/cost events (`LLM_INVOCATION_SUCCESS`,
`TOKEN_USAGE_DETAILS`, `LLM_CONFIG_RESOLVED`, …) reach Elasticsearch via stdout but are
**not** reliably in Mongo. BotProbe Trace Viewer reads ES — same path we use via curl.

**Scripts:** [`lookup_session.py`](./lookup_session.py), [`fetch_filtered_session_ids.py`](./fetch_filtered_session_ids.py)

---

## 1. The problem (before this)

Getting one conversation's data used to take 3 manual steps:

```
Production call
  → get its Session ID (a UUID, e.g. ed8b1161-b5ed-450a-8a93-fa241f78df37)
  → paste into BotProbe's Trace Viewer, click Load
  → BotProbe shows a DIFFERENT id, labeled "VOICE → 6a8ffb24c271599cf2edf886"
  → copy that id
  → paste into MongoDB Compass, search the SessionRequest collection
  → finally get the actual turn-by-turn session data
```

Slow, manual, and not something Ypervaíno's backend could ever call automatically.

---

## 2. The discovery

Reverse-engineered by directly inspecting the `AssistantSession` collection for a known
example (matched against a real BotProbe lookup to confirm). The two ids BotProbe shows
are **both already present on one `AssistantSession` document**:

| What BotProbe calls it | What it actually is in MongoDB |
|---|---|
| The **"Session ID"** you type in | `AssistantSession.voice_session_id` (a string field, the UUID) |
| The **"VOICE →"** id it shows you | `AssistantSession._id` (the document's own Mongo ObjectId) |

And critically: `AssistantSession._id` is the **same value** used as `session_id` in the
`SessionRequest` collection (the collection that holds the actual per-turn conversation data —
query, response, agent name, tool calls).

So BotProbe's whole "lookup" is really just one MongoDB query most people don't have direct
access to run themselves — it's not a separate secret system, just a document field.

## 3. The automated chain

```
Session UUID (e.g. from the production dashboard)
  → query AssistantSession where voice_session_id == that UUID
  → read that document's _id  →  this is the "voice id"
  → query SessionRequest where session_id == that voice id
  → get every turn: query, final_response, agent_name, tool_call_list, created_at
```

Two MongoDB queries for **turn-level transcript preview** (`SessionRequest`). For the full
event trace used by the pipeline, use the BotProbe API (§4).

---

## 4. Loading full event traces (BotProbe `/trace` API)

BotProbe's Trace Viewer UI calls the same backend endpoint we use programmatically:

```
GET {BOTPROBE_TRACE_BASE_URL}/trace?session_id={uuid_or_voice_id}&env=prod
```

**Example:**

```bash
curl "http://10.128.0.34:3333/trace?session_id=7d92388f-f9bc-4add-a272-59e0ab935879&env=prod"
```

**Response shape:**

```json
{
  "session_id": "6a928126e6d9cf4192db007d",
  "resolved_from": "voice",
  "events": [ { "event_type": "...", "timestamp": "...", "content": "...", "event_value": {} }, ... ]
}
```

- **`session_id` param:** BotProbe UUID (`voice_session_id`) **or** 24-char hex internal id — BotProbe resolves UUID → internal id via Mongo server-side.
- **No type filter on the API** — returns the full ES stream (~100+ event types). The Trace Viewer UI hides most types client-side (`CRITICAL_EVENT_TYPES`); curl does not.
- **Server-side exclusions only:** `KEEPALIVE_SENT`, `VAD_METRICS`, and one noisy queue log line.

Verified on a reconnect session (2026-08-29 resound): curl returned **846 events / 107 types**
including all required LLM types; Mongo `AssistantEvent` for the same session had **87 events /
11 types** and zero LLM rows.

**Env (Ypervaíno backend):**

| Var | Example | Purpose |
|-----|---------|---------|
| `BOTPROBE_TRACE_BASE_URL` | `http://10.128.0.34:3333` | Base URL for `/trace` |
| `BOTPROBE_TRACE_ENV` | `prod` | `env` query param |

Implementation reference: BotProbe `server/trace_builder.py` (`fetch_trace` → Elasticsearch scroll).

---

## 5. Using session lookup

### Setup (one-time)

Create `.env.mongo` in this folder (already gitignored — **never commit real credentials**):

```
MONGO_URI=<the real connection string, from MongoDB Compass's saved connection>
MONGO_DB_NAME=bot_prod
```

Install the one dependency:

```bash
pip3 install pymongo
```

### Run it from the command line

```bash
python3 lookup_session.py <session-uuid>
```

Example output shape:

```
voice_id: 6a8ffb24c271599cf2edf886  (13 turns)

Bot  [welcome_message]: Hi, I'm Eva, your virtual assistant...
User [Authentication]: I need to update the site address.
Bot  [Authentication]: Please hold on one moment while I look up your account...
  tools: [{'name': 'soql_query', 'arguments': '...', ...}]
...
```

### Use it as a function (for wiring into Ypervaíno itself)

```python
from lookup_session import get_session_transcript

result = get_session_transcript(mongo_uri, db_name, "ed8b1161-b5ed-450a-8a93-fa241f78df37")
# result = {
#   "botprobe_session_uuid": "...",
#   "voice_id": "6a8ffb24c271599cf2edf886",
#   "turn_count": 13,
#   "turns": [ {query, final_response, agent_name, tool_call_list, created_at}, ... ],
# }
```

For pipeline materialization, prefer `/trace` events over `AssistantEvent` or `SessionRequest`
alone — only `/trace` includes LLM cost/latency and the full debug stream.

---

## 6. Handling with care

`bot_prod` is a **real production database** with real customer conversations (names, phone
numbers, case details). Rules for anyone using this:

- **Read-only.** Nothing in `lookup_session.py` writes or deletes — keep it that way.
- **Never commit real output, real session ids, or `.env.mongo` to git.** Only the script
  itself (code, no data) belongs in this repo.
- **Don't screenshot or paste real transcript content into shared/public places** (Slack is
  fine internally, but treat it like any other customer-data handling — no public posting).
- Pull small samples for development/demo, not bulk exports.

---

## 7. Document history

| Version | Date | Notes |
|---------|------|-------|
| v1 | 2026-08-29 | Initial writeup after reverse-engineering the BotProbe id mapping via a live lookup |
| v2 | 2026-08-30 | Dual-source model: Mongo for session index/ids; BotProbe `/trace` (ES) for full events; Mongo `AssistantEvent` documented as incomplete subset |
