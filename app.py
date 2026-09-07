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
from ypervaino.config_loader import load_filter_atoms, primitive_event_map, signal_method_map
from ypervaino.data_layer import list_assistants, list_tenants
from ypervaino.log import get_logger, setup_logging
from ypervaino.settings import BOTPROBE_BASE_URL, ROOT, load_mongo_env
from ypervaino.proposals import (
    ProposalError,
    acknowledge_proposal,
    apply_shallow_proposal,
    blueprint_diff,
    get_blueprint_version,
    get_proposals_payload,
    jira_stub,
    manual_blueprint_patch,
    reject_proposal,
)
from ypervaino.blueprint_store import read_manifest
from ypervaino.study_runner import StudyRunner
from ypervaino.study_store import StudyStore, slugify

setup_logging()
log = get_logger("server")

DIR = ROOT
runner = StudyRunner()
app = FastAPI(title="Ypervaíno", version="1.0")
API = "/api/v1/ypervaino"


@app.on_event("startup")
def _warmup_on_startup() -> None:
    from ypervaino.embeddings import warmup
    from ypervaino.settings import OPENAI_EMBEDDING_MODEL, OPENAI_EMBEDDING_DIM

    if not os.environ.get("OPENAI_API_KEY"):
        log.warning("OPENAI_API_KEY not set — embeddings will fail at runtime")
        return
    log.info("OpenAI embeddings: model=%s dim=%d", OPENAI_EMBEDDING_MODEL, OPENAI_EMBEDDING_DIM)
    warmup()
    log.info("OpenAI embeddings ready")


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
    n_explore: int = 10
    n_eval: int | str = 10
    min_support: int = 10
    positive_hypothesis_good_rate_pct: float = 70
    negative_hypothesis_bad_rate_pct: float = 10
    significance_level: float = 0.05
    pairing_turn_tolerance: int = 3
    traffic_split: dict[str, Any] | None = None


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
            "description": a.get("description"),
            "value_required": a.get("value") is None and a.get("value_type") not in ("boolean",) and a.get("ui_control") not in ("toggle",),
            "value_type": a.get("value_type", "string"),
            "ui_control": a.get("ui_control", "text"),
            "default_value": a.get("value"),
            "allowed_values": a.get("allowed_values"),
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
    log.info(
        "create study title=%r type=%s tenant=%s assistant=%s n_explore=%s n_eval=%s",
        body.study_title, body.study_type, body.tenant, body.assistant_origin_id,
        body.n_explore, body.n_eval,
    )
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
        "logs_url": f"{API}/studies/{slug}/logs",
    }


@app.get(f"{API}/studies/{{slug}}/logs")
def study_logs(slug: str, tail: int = Query(100, ge=1, le=2000)):
    store = _study_or_404(slug)
    log_path = store.intermediate_dir / "pipeline.log"
    if not log_path.exists():
        return {
            "slug": slug,
            "path": f"studies/{slug}/intermediate/pipeline.log",
            "total_lines": 0,
            "lines": [],
        }
    all_lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    return {
        "slug": slug,
        "path": f"studies/{slug}/intermediate/pipeline.log",
        "total_lines": len(all_lines),
        "lines": all_lines[-tail:],
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
        "primitive_events": primitive_event_map(),
        "signal_methods": signal_method_map(plan),
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


@app.get(f"{API}/studies/{{slug}}/plots/{{filename}}")
def get_plot(slug: str, filename: str):
    store = _study_or_404(slug)
    safe_name = Path(filename).name  # no path traversal via ../
    path = store.output_dir / "plots" / safe_name
    if not path.exists():
        raise HTTPException(404, detail={"error": {"code": "NOT_FOUND", "message": "Plot not found"}})
    return FileResponse(path, media_type="image/png")


def _hypothesis_session_lists(store: StudyStore, hypothesis_id: str) -> dict[str, list[str]]:
    passed: list[str] = []
    failed: list[str] = []
    pc_dir = store.output_dir / "per_conversation"
    if not pc_dir.exists():
        return {"passed": passed, "failed": failed}
    for path in sorted(pc_dir.glob("*.json")):
        try:
            row = store.read_json(path)
        except Exception:
            continue
        sid = str(row.get("session_id") or path.stem)
        raw = (row.get("hypotheses") or {}).get(hypothesis_id)
        if isinstance(raw, dict):
            if not raw.get("applicable"):
                continue
            if raw.get("matched"):
                passed.append(sid)
            else:
                failed.append(sid)
        elif raw is True:
            passed.append(sid)
        elif raw is False:
            failed.append(sid)
    return {"passed": passed, "failed": failed}


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
    plan = {}
    plan_path = store.intermediate_dir / "analysis_plan.json"
    if plan_path.exists():
        plan = store.read_json(plan_path)
    suggested_plots = ((plan.get("quantitative") or {}).get("suggested_plots") or [])
    plot_meta = {
        p.get("id"): {
            "title": p.get("title") or p.get("id"),
            "description": p.get("description") or "",
            "template": p.get("template") or "",
        }
        for p in suggested_plots
        if p.get("id")
    }
    predicates = {}
    scope_predicates = {}
    polarities = {}
    for h in ((plan.get("qualitative") or {}).get("hypotheses") or []):
        if not h.get("id"):
            continue
        predicates[h["id"]] = h.get("predicate")
        scope_predicates[h["id"]] = h.get("scope_predicate")
        polarities[h["id"]] = h.get("polarity")
    study_req = {}
    create_path = store.input_dir / "create_study.json"
    if create_path.exists():
        study_req = store.read_json(create_path)
    hyp_thresholds = {
        "positive_hypothesis_good_rate_pct": float(
            study_req.get("positive_hypothesis_good_rate_pct") or 70
        ),
        "negative_hypothesis_bad_rate_pct": float(
            study_req.get("negative_hypothesis_bad_rate_pct") or 10
        ),
    }
    cs = data.get("cohort_sizes") or {}
    plan_aspects = {
        a.get("id"): a
        for a in ((plan.get("quantitative") or {}).get("aspects") or [])
        if a.get("id")
    }
    # UI-friendly shape for dashboard.html. `before`/`after`/`value` can be
    # present but null (single-cohort study, or no_data) -- `.get(k, default)`
    # only falls back on a *missing* key, not a null one, so check explicitly.
    aspects = []
    for a in data.get("aspects") or []:
        value = a.get("value")
        before = a.get("before")
        after = a.get("after")
        delta_pct = a.get("delta_pct")
        aspect_id = a.get("id") or a.get("name")
        plan_aspect = plan_aspects.get(aspect_id) or {}
        aspects.append({
            "id": aspect_id,
            "name": a.get("name") or aspect_id,
            "description": plan_aspect.get("description") or "",
            "components": plan_aspect.get("components") or [],
            "value": value,
            "before": value if before is None else before,
            "after": value if after is None else after,
            "delta_pct": 0 if delta_pct is None else delta_pct,
            "good_if": a.get("good_if", "down"),
            "no_data": bool(a.get("no_data")),
        })
    hypotheses_out = []
    pos_thresh = hyp_thresholds["positive_hypothesis_good_rate_pct"]
    neg_thresh = hyp_thresholds["negative_hypothesis_bad_rate_pct"]
    for h in data.get("hypotheses") or []:
        hid = h.get("id")
        polarity = h.get("polarity") or polarities.get(hid) or "positive"
        total_samples = h.get("total_samples")
        if total_samples is None:
            total_samples = sum((h.get("rates") or {}).get(k, {}).get("total", 0) for k in ("all", "before", "after"))
            if not total_samples:
                total_samples = cs.get("total")
        applicable_samples = h.get("applicable_samples")
        if applicable_samples is None:
            applicable_samples = total_samples
        conditional_rate = h.get("conditional_rate")
        if conditional_rate is None:
            conditional_rate = (h.get("rates") or {}).get("all", {}).get("rate", 0)
        conditional_rate_pct = h.get("conditional_rate_pct")
        if conditional_rate_pct is None:
            conditional_rate_pct = round(float(conditional_rate or 0) * 100, 1)
        outcome = h.get("outcome")
        if not outcome:
            from ypervaino.hypothesis_predicate import hypothesis_outcome, infer_polarity

            pol = infer_polarity({"polarity": polarity, "title": h.get("title")})
            outcome = (
                "neutral"
                if not applicable_samples
                else hypothesis_outcome(
                    pol,
                    float(conditional_rate_pct),
                    positive_good_rate_pct=pos_thresh,
                    negative_bad_rate_pct=neg_thresh,
                )
            )
        hypotheses_out.append({
            **h,
            "predicate": h.get("predicate") or predicates.get(hid),
            "scope_predicate": h.get("scope_predicate") or scope_predicates.get(hid),
            "polarity": polarity,
            "total_samples": total_samples,
            "applicable_samples": applicable_samples,
            "conditional_rate": conditional_rate,
            "conditional_rate_pct": conditional_rate_pct,
            "outcome": outcome,
            "session_lists": _hypothesis_session_lists(store, hid) if hid else {"passed": [], "failed": []},
        })
    study_type = data.get("study_type") or "single_cohort"
    artifacts = data.get("artifacts") or {}
    return {
        "status": meta["status"],
        "study_type": study_type,
        "evaluation_result": data,
        "cohort_sizes": cs,
        "aspects": aspects,
        "hypotheses": hypotheses_out,
        "narrative": artifacts.get("narrative_summary"),
        "plots": artifacts.get("plots") or {},
        "plot_meta": plot_meta,
        "hypothesis_thresholds": hyp_thresholds,
        "botprobe_base_url": BOTPROBE_BASE_URL.rstrip("/"),
        "primitive_events": primitive_event_map(),
        "signal_methods": signal_method_map(plan),
    }


def _proposal_error(exc: ProposalError):
    detail = {"error": {"code": exc.code, "message": exc.message}}
    detail["error"].update(exc.extra)
    raise HTTPException(exc.status, detail=detail)


@app.get(f"{API}/studies/{{slug}}/proposals")
def get_proposals(slug: str):
    store = _study_or_404(slug)
    try:
        return get_proposals_payload(store)
    except ProposalError as e:
        _proposal_error(e)


@app.post(f"{API}/studies/{{slug}}/proposals/generate")
def generate_proposals_route(slug: str, force: bool = Query(False)):
    store = _study_or_404(slug)
    try:
        from ypervaino.proposal_generator import read_generation_status

        gen = read_generation_status(store)
        if gen.get("status") == "ready" and not force:
            return get_proposals_payload(store)
        if gen.get("status") != "generating":
            runner.generate_proposals(slug, force=force)
            gen = read_generation_status(store)
        return JSONResponse({
            "slug": slug,
            "generation": {
                "status": gen.get("status", "generating"),
                "started_at": gen.get("started_at"),
                "poll_url": f"{API}/studies/{slug}/proposals",
            },
        }, status_code=202)
    except ProposalError as e:
        _proposal_error(e)
    except ValueError as e:
        raise HTTPException(409, detail={"error": {"code": "INVALID_STATE", "message": str(e)}})


@app.get(f"{API}/studies/{{slug}}/blueprint/manifest")
def blueprint_manifest(slug: str):
    store = _study_or_404(slug)
    return read_manifest(store)


@app.get(f"{API}/studies/{{slug}}/blueprint/versions/{{version}}")
def blueprint_version(slug: str, version: str):
    store = _study_or_404(slug)
    try:
        return get_blueprint_version(store, version)
    except FileNotFoundError as e:
        raise HTTPException(404, detail={"error": {"code": "NOT_FOUND", "message": str(e)}})


@app.get(f"{API}/studies/{{slug}}/blueprint/diff")
def blueprint_diff_route(
    slug: str,
    from_version: str = Query(..., alias="from"),
    to_version: str = Query(..., alias="to"),
    target_key: str = Query(...),
):
    store = _study_or_404(slug)
    try:
        return blueprint_diff(store, from_version, to_version, target_key)
    except FileNotFoundError as e:
        raise HTTPException(404, detail={"error": {"code": "NOT_FOUND", "message": str(e)}})


class RejectBody(BaseModel):
    reason: str | None = None


class BlueprintPatchBody(BaseModel):
    target: dict[str, Any]
    patch: dict[str, Any]
    note: str | None = None


@app.post(f"{API}/studies/{{slug}}/proposals/{{proposal_id}}/apply")
def apply_proposal(slug: str, proposal_id: str):
    store = _study_or_404(slug)
    try:
        return apply_shallow_proposal(store, proposal_id)
    except ProposalError as e:
        _proposal_error(e)


@app.post(f"{API}/studies/{{slug}}/proposals/{{proposal_id}}/reject")
def reject_proposal_route(slug: str, proposal_id: str, body: RejectBody | None = None):
    store = _study_or_404(slug)
    try:
        return reject_proposal(store, proposal_id, (body.reason if body else None))
    except ProposalError as e:
        _proposal_error(e)


@app.post(f"{API}/studies/{{slug}}/proposals/{{proposal_id}}/acknowledge")
def acknowledge_proposal_route(slug: str, proposal_id: str):
    store = _study_or_404(slug)
    try:
        return acknowledge_proposal(store, proposal_id)
    except ProposalError as e:
        _proposal_error(e)


@app.post(f"{API}/studies/{{slug}}/proposals/{{proposal_id}}/jira-stub")
def jira_stub_route(slug: str, proposal_id: str):
    store = _study_or_404(slug)
    try:
        return jira_stub(store, proposal_id)
    except ProposalError as e:
        _proposal_error(e)


@app.post(f"{API}/studies/{{slug}}/blueprint/patch")
def blueprint_patch_route(slug: str, body: BlueprintPatchBody):
    store = _study_or_404(slug)
    try:
        return manual_blueprint_patch(store, body.target, body.patch, body.note)
    except ProposalError as e:
        _proposal_error(e)


# Static pages
@app.get("/")
def index():
    return FileResponse(DIR / "new_study.html")


@app.get("/explore")
def page_explore():
    return FileResponse(DIR / "explore.html", headers={"Cache-Control": "no-cache"})


@app.get("/results")
def page_results():
    return FileResponse(DIR / "dashboard.html", headers={"Cache-Control": "no-cache"})


@app.get("/proposals")
def page_proposals():
    return FileResponse(DIR / "proposals.html")


@app.get("/sessions")
def page_sessions():
    return FileResponse(DIR / "sessions.html")


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8765"))
    log.info("starting Ypervaíno on http://0.0.0.0:%d (LOG_LEVEL=%s)", port, os.environ.get("LOG_LEVEL", "INFO"))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=False, log_level="warning")
