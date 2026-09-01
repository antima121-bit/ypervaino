"""Ypervaíno FastAPI server — run: python3 app.py"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from argparse import Namespace
from datetime import datetime

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from fetch_filtered_session_ids import fetch_filtered_session_ids
from lookup_session import get_session_transcript
from ypervaino.config_loader import load_filter_atoms
from ypervaino.data_layer import list_assistants, list_tenants
from ypervaino.settings import ROOT, load_mongo_env
from ypervaino.study_runner import StudyRunner
from ypervaino.study_store import StudyStore, slugify

DIR = ROOT
runner = StudyRunner()
app = FastAPI(title="Ypervaíno", version="1.0")
API = "/api/v1/ypervaino"


class DateRange(BaseModel):
    start: str
    end: str


class CreateStudyRequest(BaseModel):
    study_title: str
    study_type: str = Field(pattern="^(comparative|single_cohort)$")
    tenant: str
    assistant_origin_id: str
    channel: str = "voice"
    change_description: str = ""
    pr_link: str | None = None
    assistant_id: str | None = None
    cohort_filters: list[dict[str, Any]] = []
    date_range: DateRange | None = None
    date_range_before: DateRange | None = None
    date_range_after: DateRange | None = None
    n_explore: int = 100
    n_eval: int | str = "all"
    min_support: int = 10


def _mongo():
    env = load_mongo_env()
    if not env.get("MONGO_URI"):
        raise HTTPException(503, detail={"error": {"code": "UPSTREAM_ERROR", "message": "MONGO_URI not configured"}})
    return env


def _session_query_args(
    study_type: str = "single_cohort",
    tenant: str = "",
    assistant_origin_id: str = "",
    assistant_id: str | None = None,
    channel: str = "voice",
    limit: int = 100,
    date_range_start: str | None = None,
    date_range_end: str | None = None,
    date_range_before_start: str | None = None,
    date_range_before_end: str | None = None,
    date_range_after_start: str | None = None,
    date_range_after_end: str | None = None,
) -> Namespace:
    def parse_dt(s: str | None):
        return datetime.fromisoformat(s) if s else None

    return Namespace(
        study_type=study_type,
        tenant=tenant,
        assistant_origin_id=assistant_origin_id,
        assistant_id=assistant_id,
        channel=channel,
        limit=limit,
        date_range_start=parse_dt(date_range_start),
        date_range_end=parse_dt(date_range_end),
        date_range_before_start=parse_dt(date_range_before_start),
        date_range_before_end=parse_dt(date_range_before_end),
        date_range_after_start=parse_dt(date_range_after_start),
        date_range_after_end=parse_dt(date_range_after_end),
    )


def _study_or_404(slug: str) -> StudyStore:
    store = StudyStore(slug)
    if not store.meta_path().exists():
        raise HTTPException(404, detail={"error": {"code": "NOT_FOUND", "message": f"Study {slug} not found"}})
    return store


@app.get(f"{API}/tenants")
def get_tenants():
    env = _mongo()
    return {"tenants": list_tenants(env["MONGO_URI"], env["MONGO_DB_NAME"])}


@app.get(f"{API}/assistants")
def get_assistants(tenant: str):
    env = _mongo()
    return {"assistants": list_assistants(env["MONGO_URI"], env["MONGO_DB_NAME"], tenant)}


@app.get(f"{API}/config/filter-atoms")
def get_filter_atoms():
    atoms = []
    for a in load_filter_atoms():
        atoms.append({
            "atom_id": a["id"],
            "label": a["label"],
            "value_required": a.get("value_type") not in ("boolean",) and not a.get("value"),
            "value_type": a.get("value_type", "string"),
        })
    return {"atoms": atoms}


@app.get(f"{API}/session_ids")
def session_ids(
    study_type: str = "single_cohort",
    tenant: str = Query(...),
    assistant_origin_id: str = Query(...),
    channel: str = "voice",
    assistant_id: str | None = None,
    limit: int = 100,
    date_range_start: str | None = None,
    date_range_end: str | None = None,
    date_range_before_start: str | None = None,
    date_range_before_end: str | None = None,
    date_range_after_start: str | None = None,
    date_range_after_end: str | None = None,
):
    env = _mongo()
    args = _session_query_args(
        study_type=study_type,
        tenant=tenant,
        assistant_origin_id=assistant_origin_id,
        assistant_id=assistant_id,
        channel=channel,
        limit=limit,
        date_range_start=date_range_start,
        date_range_end=date_range_end,
        date_range_before_start=date_range_before_start,
        date_range_before_end=date_range_before_end,
        date_range_after_start=date_range_after_start,
        date_range_after_end=date_range_after_end,
    )
    return fetch_filtered_session_ids(env["MONGO_URI"], env["MONGO_DB_NAME"], args)


@app.get(f"{API}/session_detail")
def session_detail(session_id: str = Query(...)):
    env = _mongo()
    result = get_session_transcript(env["MONGO_URI"], env["MONGO_DB_NAME"], session_id)
    if "error" in result:
        raise HTTPException(404, detail={"error": {"code": "NOT_FOUND", "message": result["error"]}})
    return result


@app.get(f"{API}/studies/check-title")
def check_title(title: str):
    slug = slugify(title)
    available = not StudyStore.slug_exists(slug)
    return {"title": title, "slug": slug, "available": available}


@app.post(f"{API}/studies", status_code=202)
def create_study(body: CreateStudyRequest):
    if body.study_type == "single_cohort" and not body.date_range:
        raise HTTPException(400, detail={"error": {"code": "VALIDATION_ERROR", "message": "date_range required"}})
    if body.study_type == "comparative" and (not body.date_range_before or not body.date_range_after):
        raise HTTPException(400, detail={"error": {"code": "VALIDATION_ERROR", "message": "before/after date ranges required"}})
    if body.study_type == "comparative" and body.n_explore % 2 != 0:
        raise HTTPException(400, detail={"error": {"code": "VALIDATION_ERROR", "message": "n_explore must be even for comparative"}})
    req = body.model_dump()
    meta = runner.create_study(req)
    slug = meta["slug"]
    return {
        "slug": slug,
        "title": meta["title"],
        "status": meta["status"],
        "poll_url": f"{API}/studies/{slug}/status",
    }


@app.get(f"{API}/studies/{{slug}}")
def get_study(slug: str):
    return _study_or_404(slug).read_meta()


@app.get(f"{API}/studies/{{slug}}/status")
def study_status(slug: str):
    store = _study_or_404(slug)
    meta = store.read_meta()
    return {
        "slug": slug,
        "status": meta["status"],
        "error": meta.get("error"),
        "progress_hints": store.progress_hints(),
    }


@app.get(f"{API}/studies/{{slug}}/explore")
def explore(slug: str):
    store = _study_or_404(slug)
    meta = store.read_meta()
    if meta["status"] == "created":
        raise HTTPException(409, detail={"error": {"code": "INVALID_STATE", "message": "Plan not ready yet"}})
    plan_path = store.intermediate_dir / "analysis_plan.json"
    if not plan_path.exists():
        raise HTTPException(409, detail={"error": {"code": "INVALID_STATE", "message": "Analysis plan missing"}})
    cohort = {}
    cs = store.intermediate_dir / "cohort_stats.json"
    if cs.exists():
        cohort = store.read_json(cs)
    plan = store.read_json(plan_path)
    manifest_path = store.intermediate_dir / "s_explore" / "manifest.json"
    samples = []
    if manifest_path.exists():
        manifest = store.read_json(manifest_path)
        for sid in (manifest.get("session_ids") or [])[:6]:
            dp = store.intermediate_dir / "s_explore" / f"{sid}.digest.json"
            if dp.exists():
                d = store.read_json(dp)
                samples.append({
                    "session_id": sid,
                    "transcript": [{"speaker": t.get("speaker"), "text": t.get("text")} for t in (d.get("transcript") or [])[:6]],
                })
    return {
        "meta": meta,
        "cohort_stats": cohort,
        "analysis_plan": plan,
        "samples": samples,
        "llm": {
            "exploration_summary": plan.get("exploration_summary") or "",
            "aspects": ((plan.get("quantitative") or {}).get("aspects") or []),
            "suggested_plots": ((plan.get("quantitative") or {}).get("suggested_plots") or []),
            "suggested_tables": ((plan.get("quantitative") or {}).get("suggested_tables") or []),
            "hypotheses": ((plan.get("qualitative") or {}).get("hypotheses") or []),
            "error": None,
        },
    }


@app.post(f"{API}/studies/{{slug}}/execute", status_code=202)
def execute_study(slug: str):
    store = _study_or_404(slug)
    meta = store.read_meta()
    if meta["status"] != "explored":
        raise HTTPException(409, detail={"error": {"code": "INVALID_STATE", "message": f"Cannot execute from status {meta['status']}"}})
    runner.execute(slug)
    return {"slug": slug, "status": "running", "poll_url": f"{API}/studies/{slug}/status"}


@app.get(f"{API}/studies/{{slug}}/results")
def results(slug: str):
    store = _study_or_404(slug)
    meta = store.read_meta()
    if meta["status"] not in ("complete", "running"):
        raise HTTPException(409, detail={"error": {"code": "INVALID_STATE", "message": "Results not ready"}})
    rp = store.output_dir / "evaluation_result.json"
    if not rp.exists():
        return {"status": meta["status"], "error": "Evaluation still running"}
    data = store.read_json(rp)
    is_comparative = data.get("is_comparative", data.get("study_type") == "comparative")
    # UI-friendly shape for dashboard.html. `before`/`after` are None on a
    # single-cohort result (no real comparison exists) -- use `.get(k) is None`
    # rather than `.get(k, default)`, since the key is present but null, not
    # missing, and `.get` only falls back on a missing key.
    aspects = []
    for a in data.get("aspects") or []:
        value = a.get("value")
        before = a.get("before")
        after = a.get("after")
        aspects.append({
            "name": a.get("name") or a.get("id"),
            "value": value,
            "before": value if before is None else before,
            "after": value if after is None else after,
            "delta_pct": a.get("delta_pct") if a.get("delta_pct") is not None else 0,
            "good_if": a.get("good_if", "down"),
            "no_data": bool(a.get("no_data")),
        })
    cs = data.get("cohort_sizes") or {}
    return {
        "status": meta["status"],
        "is_comparative": is_comparative,
        "evaluation_result": data,
        "cohort_sizes": cs,
        "aspects": aspects,
        "hypotheses": data.get("hypotheses") or [],
        "narrative": (data.get("artifacts") or {}).get("narrative_summary"),
    }


# Static pages
@app.get("/")
def index():
    return FileResponse(DIR / "new_study.html")


@app.get("/explore")
def page_explore():
    return FileResponse(DIR / "explore.html")


@app.get("/results")
def page_results():
    return FileResponse(DIR / "dashboard.html")


@app.get("/sessions")
def page_sessions():
    return FileResponse(DIR / "sessions.html")


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8765"))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=False)
