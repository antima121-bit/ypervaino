# Analysis Tool Web UI

## Run locally

From `analysis_tool/` (requires `analysis_tool/.env` with Mongo, OpenAI, BotProbe):

```bash
make web
# or
uvicorn web.app:app --host 0.0.0.0 --port 8080
```

Open `http://localhost:8080/`.

Each evaluation run writes artifacts under `analysis_tool/runs/{run_id}/study/`.

## API

- `GET /api/llm-options` — LLM dropdown values
- `POST /api/runs` — start pipeline (JSON body matches the form)
- `GET /api/runs/{run_id}` — status
- `GET /api/runs/{run_id}/logs/stream` — SSE log stream (ANSI stripped)
- `GET /api/runs/{run_id}/results` — dashboard JSON (success only)
