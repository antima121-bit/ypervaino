from __future__ import annotations

import traceback
from typing import Any

from ypervaino.log import get_logger
from ypervaino.proposal_context import load_generation_context
from ypervaino.proposal_deep import fetch_repo_snippets, generate_deep_proposals
from ypervaino.proposal_shallow import generate_shallow_proposals
from ypervaino.proposal_validate import post_process_deep, post_process_shallow
from ypervaino.study_store import StudyStore, now_iso

_log = get_logger("proposal_generator")


def _status_path(store: StudyStore):
    return store.intermediate_dir / "proposal_generation" / "status.json"


def _bundle_path(store: StudyStore):
    return store.output_dir / "proposal_bundle.json"


def read_generation_status(store: StudyStore) -> dict[str, Any]:
    path = _status_path(store)
    if not path.exists():
        return {"status": "not_started"}
    return store.read_json(path)


def write_generation_status(store: StudyStore, status: dict[str, Any]) -> None:
    store.write_json(_status_path(store), status)


def _collect_findings(shallow: list[dict], deep: list[dict]) -> list[str]:
    ids: set[str] = set()
    for p in shallow + deep:
        evidence = p.get("evidence")
        if isinstance(evidence, str):
            items: list[Any] = [evidence]
        elif isinstance(evidence, list):
            items = evidence
        else:
            items = []
        for ev in items:
            if isinstance(ev, str):
                if ev.strip():
                    ids.add(ev.strip())
                continue
            if not isinstance(ev, dict):
                continue
            fid = ev.get("finding_id")
            if fid:
                ids.add(str(fid))
            elif ev.get("summary"):
                ids.add(str(ev["summary"])[:120])
    return sorted(ids)


def _build_summary(shallow: list[dict], deep: list[dict], ctx: dict[str, Any]) -> str:
    n_s, n_d = len(shallow), len(deep)
    if n_s == 0 and n_d == 0:
        return "No actionable proposals were generated from this evaluation."
    parts = []
    if n_s:
        parts.append(f"{n_s} VA Blueprint change{'s' if n_s != 1 else ''} you can apply individually")
    if n_d:
        parts.append(f"{n_d} backend or pipeline recommendation{'s' if n_d != 1 else ''} outside blueprint scope")
    return f"Generated {' and '.join(parts)} for study {ctx.get('study_slug', '')}."


def post_process_bundle(
    shallow: list[dict[str, Any]],
    deep: list[dict[str, Any]],
    ctx: dict[str, Any],
    store: StudyStore,
) -> dict[str, Any]:
    shallow_ok = post_process_shallow(shallow, store)
    deep_ok = post_process_deep(deep)
    findings = _collect_findings(shallow_ok, deep_ok)
    return {
        "schema_version": "1.0",
        "study_slug": store.slug,
        "generated_at": now_iso(),
        "summary": _build_summary(shallow_ok, deep_ok, ctx),
        "inputs": {
            "evaluation_result_path": "output/evaluation_result.json",
            "analysis_plan_path": "intermediate/analysis_plan.json",
            "blueprint_baseline_version": "v0001",
            "blueprint_current_version": ctx.get("blueprint_current_version") or "v0001",
            "change_context_path": "intermediate/change_context.json",
            "dialog_flow_path": "intermediate/blueprint/dialog_flow.json",
            "recommendations": ctx.get("recommendations") or [],
            "aspect_count": len(ctx.get("aspect_results") or []),
            "hypothesis_count": len(ctx.get("hypothesis_results") or []),
        },
        "shallow_proposals": shallow_ok,
        "deep_proposals": deep_ok,
        "stats": {
            "shallow_count": len(shallow_ok),
            "deep_count": len(deep_ok),
            "findings_addressed": findings,
        },
    }


def run_phase4(store: StudyStore) -> None:
    started = now_iso()
    write_generation_status(store, {
        "status": "generating",
        "started_at": started,
        "finished_at": None,
        "error": None,
    })
    _log.info("[Phase 4] proposal generation started slug=%s", store.slug)
    try:
        ctx = load_generation_context(store)
        shallow = generate_shallow_proposals(ctx)
        snippets = fetch_repo_snippets(ctx)
        shallow_titles = [p.get("title") for p in shallow if p.get("title")]
        deep = generate_deep_proposals(ctx, snippets, shallow_titles)
        bundle = post_process_bundle(shallow, deep, ctx, store)
        store.write_json(_bundle_path(store), bundle)
        write_generation_status(store, {
            "status": "ready",
            "started_at": started,
            "finished_at": now_iso(),
            "error": None,
            "bundle_path": "output/proposal_bundle.json",
        })
        _log.info(
            "[Phase 4] complete — %d shallow, %d deep proposals",
            bundle["stats"]["shallow_count"],
            bundle["stats"]["deep_count"],
        )
    except Exception as e:
        _log.exception("[Phase 4] failed")
        write_generation_status(store, {
            "status": "failed",
            "started_at": started,
            "finished_at": now_iso(),
            "error": f"{type(e).__name__}: {e}\n{traceback.format_exc()}",
        })
        raise
