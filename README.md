# Ypervaíno

Production voice-bot conversation analysis — comparative impact studies and pure discovery over real Mongo + BotProbe data.

## Architecture (spec-aligned)

| Phase | Components |
|-------|------------|
| **0** | Mongo scope filter, BotProbe traces, FeatureComputer, cohort predicates, blueprint, ChangeContextResolver (ReAct), IntentLexicon + classifier, stratified n_eval |
| **1** | ExplorationSampler — strata, SBERT medoid/farthest-point, comparative pairing |
| **2a** | DigestBuilder (parallel, rule-derived anomalies) |
| **2b** | PlanSynthesizer (gpt-4.1) + schema validation + retry |
| **3** | SignalExecutor, significance tests, counter-examples, ArtifactRenderer (CSV + PNG), narrative |

See [`architecture.md`](./architecture.md), [`sample_gothrough.md`](./sample_gothrough.md).

## Run

```bash
pip3 install -r requirements.txt
cp .env.example .env   # OPENAI_API_KEY, PRODUCTION_SERVICE_TOKEN, BotProbe URL
# .env.mongo for Mongo
python3 app.py
```

Open http://localhost:8765/

Studies persist under `./studies/{slug}/` including `intermediate/timing.jsonl`.

## Key env vars

- `OPENAI_API_KEY` — plan synthesis, intent lexicon, narrative
- `PRODUCTION_SERVICE_TOKEN` — VA blueprint at `bot.thelevel.ai`
- `BOTPROBE_TRACE_BASE_URL` — full event traces
- `MAX_TRACE_SESSIONS` — safety cap per cohort (default 200)

First run downloads SBERT model (`all-MiniLM-L6-v2`, ~90MB).
