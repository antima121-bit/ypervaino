# Mongo Session Lookup — automating BotProbe → MongoDB

**Solves:** the "Mongo thing figure out" task — how to go from a production call's
Session/Conversation ID to its full conversation data, without manually going through
BotProbe's UI and MongoDB Compass every time.

**Script:** [`lookup_session.py`](./lookup_session.py)

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

Two MongoDB queries. No BotProbe UI, no Compass, no copy-pasting between tools.

---

## 4. Using it

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

This is the shape `server.py` would consume once Ypervaíno is wired to real production data
instead of the seeded SQLite demo data — see `README.md`'s "Known gaps" section.

---

## 5. Handling with care

`bot_prod` is a **real production database** with real customer conversations (names, phone
numbers, case details). Rules for anyone using this:

- **Read-only.** Nothing in `lookup_session.py` writes or deletes — keep it that way.
- **Never commit real output, real session ids, or `.env.mongo` to git.** Only the script
  itself (code, no data) belongs in this repo.
- **Don't screenshot or paste real transcript content into shared/public places** (Slack is
  fine internally, but treat it like any other customer-data handling — no public posting).
- Pull small samples for development/demo, not bulk exports.

---

## 6. Document history

| Version | Date | Notes |
|---------|------|-------|
| v1 | 2026-08-29 | Initial writeup after reverse-engineering the BotProbe id mapping via a live lookup |
