# Ypervaíno

Analyze voice-bot conversations at scale — measure the impact of a backend change
(model swap, guardrails, prompt change…) or discover hidden patterns in production traffic.

See [`hackthon.md`](./hackthon.md) for the formal model and [`architecture.md`](./architecture.md) for the pipeline design.

## What's in here

| Component | Role |
|-----------|------|
| `app.py` | FastAPI server — study lifecycle API + static UI |
| `ypervaino/` | Pipeline (phases 0–3), feature computation, LLM client, study store |
| `config/` | Event schema, primitives, filter atoms, pricing, artifact templates |
| `new_study.html`, `explore.html`, `dashboard.html`, `sessions.html` | 3-tab flow + session browser |
| `fetch_filtered_session_ids.py`, `lookup_session.py` | Mongo session discovery & transcript lookup |
| `server.py` | Legacy demo handler (prefer `app.py`) |

**Data sources (production):**

- **Mongo** `AssistantSession` — session discovery (tenant, dates, assistant)
- **BotProbe** `GET /trace?session_id=…&env=prod` — full event logs (Elasticsearch)
- **VA Blueprint** `POST /service/va-blueprint/extract_blueprint` — assistant structure

See [`MONGO_LOOKUP.md`](./MONGO_LOOKUP.md) and [`sample_gothrough.md`](./sample_gothrough.md).

## Running

```bash
cd ypervaino
pip3 install -r requirements.txt
cp .env.example .env          # OPENAI_API_KEY, BotProbe URL, blueprint URL
# .env.mongo with MONGO_URI + MONGO_DB_NAME (gitignored)
python3 app.py
```

Open **http://localhost:8765/**

1. **New Study** — submit comparative or discovery study (async phases 0–2)
2. **Explore** — review LLM-generated analysis plan, click **Execute plan**
3. **Results** — aspect deltas, hypothesis rates, narrative summary
4. **Sessions** — browse sessions by tenant/date, view transcripts

Studies persist under `./studies/{slug}/`.

## Specs (source of truth)

- [`input_schema.md`](./input_schema.md) — study form fields
- [`output_schema.md`](./output_schema.md) — pipeline artifacts
- [`api.md`](./api.md) — HTTP API
- [`UI_design.md`](./UI_design.md) — tab flow

## v1 notes

- Phase 0 traces up to `MAX_TRACE_SESSIONS` (default 200) per cohort
- Exploration sampling is random (not embedding-medoid)
- Change context resolver is a stub; blueprint fetched via HTTP
- Artifact renderer writes CSV tables; PNG plots deferred
- Cohort filter atoms supported in API; UI wiring optional
