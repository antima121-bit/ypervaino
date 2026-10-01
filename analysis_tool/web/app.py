"""FastAPI app: form UI, log streaming, results dashboard."""

from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

TOOL_DIR = Path(__file__).resolve().parent.parent
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

from study_config import config_from_form, config_to_yaml  # noqa: E402
from web.llm_models import (  # noqa: E402
    DEFAULT_API_MODEL,
    DEFAULT_EFFORT,
    llm_form_options,
    resolve_model_name,
)
from web.results_loader import load_full_results  # noqa: E402
from web.log_util import collapse_trace_progress_lines  # noqa: E402
from web.run_manager import RunManager  # noqa: E402

WEB_DIR = Path(__file__).resolve().parent
STATIC_DIR = WEB_DIR / "static"

app = FastAPI(title="Analysis Tool", version="1.0.0")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

run_manager = RunManager()

DEFAULT_SESSION_LIMIT = 10_000

_STUDY_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")
_DATE_RE = re.compile(r"^\d{2}-\d{2}-\d{4}$")


class StartRunRequest(BaseModel):
    study_name: str = Field(..., min_length=1, max_length=128)
    tenant_name: str = Field(..., min_length=1, max_length=128)
    assistant_origin_id: str = Field(..., min_length=1, max_length=128)
    date_range_start: str
    date_range_end: str
    hypothesis: str = Field(..., min_length=1)
    api_model: str = DEFAULT_API_MODEL
    reasoning_effort: str = DEFAULT_EFFORT
    concurrency: int = Field(default=10, ge=1, le=256)
    limit: int = Field(default=DEFAULT_SESSION_LIMIT, ge=1, le=1_000_000)

    @field_validator("study_name")
    @classmethod
    def validate_study_name(cls, v: str) -> str:
        v = v.strip()
        if not _STUDY_NAME_RE.match(v):
            raise ValueError("study_name may only contain letters, numbers, underscore, hyphen")
        return v

    @field_validator("date_range_start", "date_range_end")
    @classmethod
    def validate_date(cls, v: str) -> str:
        v = v.strip()
        if not _DATE_RE.match(v):
            raise ValueError("dates must be DD-MM-YYYY")
        return v


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/results/{run_id}")
async def results_page(run_id: str) -> FileResponse:
    return FileResponse(STATIC_DIR / "results.html")


@app.get("/api/llm-options")
async def api_llm_options() -> dict[str, Any]:
    return llm_form_options()


def _runs_list_payload() -> dict[str, Any]:
    return {"runs": run_manager.list_runs()}


@app.get("/api/runs")
@app.get("/api/runs/list")
async def api_list_runs() -> dict[str, Any]:
    return _runs_list_payload()


@app.delete("/api/runs")
async def api_delete_all_runs() -> dict[str, Any]:
    deleted = run_manager.delete_all_runs()
    return {"deleted": deleted}


@app.post("/api/runs")
async def api_start_run(body: StartRunRequest) -> dict[str, Any]:
    try:
        model_name = resolve_model_name(body.api_model, body.reasoning_effort)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        cfg = config_from_form(
            study_name=body.study_name,
            tenant_name=body.tenant_name,
            assistant_origin_id=body.assistant_origin_id,
            date_range_start=body.date_range_start,
            date_range_end=body.date_range_end,
            hypothesis=body.hypothesis,
            model_name=model_name,
            concurrency=body.concurrency,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if cfg.date_range_start > cfg.date_range_end:
        raise HTTPException(status_code=400, detail="date_range_start must be on or before date_range_end")

    config_text = config_to_yaml(cfg)

    form_snapshot = body.model_dump()
    form_snapshot["model_name"] = model_name

    rec = run_manager.start_run(
        config_yaml_text=config_text,
        form=form_snapshot,
        session_limit=body.limit,
    )
    return {"run_id": rec.run_id, "status": rec.status}


@app.delete("/api/runs/{run_id}")
async def api_delete_run(run_id: str) -> dict[str, Any]:
    if not run_manager.delete_run(run_id):
        raise HTTPException(status_code=404, detail="run not found")
    return {"deleted": run_id}


@app.get("/api/runs/{run_id}")
async def api_run_status(run_id: str) -> dict[str, Any]:
    rec = run_manager.get(run_id)
    if not rec:
        raise HTTPException(status_code=404, detail="run not found")
    return rec.to_public_dict()


@app.get("/api/runs/{run_id}/logs/stream")
async def api_log_stream(run_id: str) -> StreamingResponse:
    rec = run_manager.get(run_id)
    if not rec:
        raise HTTPException(status_code=404, detail="run not found")

    async def event_generator():
        queue: asyncio.Queue[tuple[str, bool] | None] = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def push(line: str, replace_last: bool) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, (line, replace_last))

        replay = collapse_trace_progress_lines(rec.read_existing_logs())
        for line in replay:
            yield f"data: {json.dumps({'line': line})}\n\n"

        rec.subscribe(push)
        try:
            while True:
                if rec.status != "running":
                    await asyncio.sleep(0.2)
                    while not queue.empty():
                        item = queue.get_nowait()
                        if item is None:
                            continue
                        line, replace_last = item
                        yield f"data: {json.dumps({'line': line, 'replace_last': replace_last})}\n\n"
                    break
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=1.0)
                    if item is None:
                        continue
                    line, replace_last = item
                    yield f"data: {json.dumps({'line': line, 'replace_last': replace_last})}\n\n"
                except asyncio.TimeoutError:
                    continue
        finally:
            rec.unsubscribe(push)

        done = json.dumps(
            {
                "event": "done",
                "status": rec.status,
                "exit_code": rec.exit_code,
            }
        )
        yield f"data: {done}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/runs/{run_id}/results")
async def api_run_results(run_id: str) -> dict[str, Any]:
    rec = run_manager.get(run_id)
    if not rec:
        raise HTTPException(status_code=404, detail="run not found")
    if rec.status != "success":
        raise HTTPException(status_code=409, detail="run did not complete successfully")
    return load_full_results(rec.study_dir)
