from __future__ import annotations

import json
import random
from typing import Any

from ypervaino.artifacts import render_plots, render_tables
from ypervaino.change_context import resolve_change_context
from ypervaino.config_loader import load_artifact_templates, load_filter_atoms
from ypervaino.data_layer import (
    fetch_blueprint,
    fetch_session_id_list,
    load_or_fetch_conversation,
    parse_dt,
    summarize_blueprint,
)
from ypervaino.digest import build_digests_parallel, pick_full_transcripts_for_plan
from ypervaino.embeddings import apply_opening_embeddings
from ypervaino.evaluation import run_evaluation
from ypervaino.exploration import build_exploration_manifest
from ypervaino.features import compute_features
from ypervaino.intent import apply_intent_to_features, build_intent_lexicon
from ypervaino.llm_client import LLMClient
from ypervaino.parallel import run_parallel, worker_count
from ypervaino.plan_validator import PlanValidationError, validate_plan
from ypervaino.sampling import stratified_subsample
from ypervaino.settings import MAX_TRACE_SESSIONS
from ypervaino.study_store import StudyStore
from ypervaino.timing import StudyTimer


def compile_predicate(filters: list[dict]) -> list[dict]:
    atoms = {a["id"]: a for a in load_filter_atoms()}
    compiled = []
    for f in filters or []:
        atom = atoms.get(f.get("atom_id") or f.get("id"))
        if atom:
            compiled.append({**atom, "user_value": f.get("value")})
    return compiled


from ypervaino.pipeline_filters import passes_filters


def _apply_traffic_split(fv: dict, traffic_split: dict | None) -> bool:
    if not traffic_split:
        return True
    want = traffic_split.get("value")
    got = fv.get("traffic_split_variant")
    return got == want if want is not None else True


def _cap_ids(ids: list[str], n_eval: Any) -> list[str]:
    cap = MAX_TRACE_SESSIONS if n_eval in (None, "all") else int(n_eval)
    if len(ids) <= cap:
        return ids
    random.shuffle(ids)
    return ids[:cap]


def phase0_cohort(store: StudyStore, req: dict[str, Any], timer: StudyTimer) -> dict[str, Any]:
    tenant = req["tenant"]
    assistant_origin_id = req["assistant_origin_id"]
    channel = req.get("channel") or "voice"
    n_eval = req.get("n_eval", "all")
    compiled = compile_predicate(req.get("cohort_filters") or [])
    traffic_split = req.get("traffic_split")
    timer.log.info(
        "Phase 0: cohort discovery tenant=%s assistant=%s filters=%d traffic_split=%s",
        tenant, assistant_origin_id, len(compiled), bool(traffic_split),
    )

    def window_ids(start_s: str, end_s: str) -> list[str]:
        return fetch_session_id_list(
            tenant, assistant_origin_id, channel, parse_dt(start_s), parse_dt(end_s),
            assistant_id=req.get("assistant_id"), limit=None,
        )

    with timer.track("0", "MongoSessionIndex"):
        if req["study_type"] == "comparative":
            before_raw = window_ids(req["date_range_before"]["start"], req["date_range_before"]["end"])
            after_raw = window_ids(req["date_range_after"]["start"], req["date_range_after"]["end"])
            cohorts_raw = {"before": _cap_ids(before_raw, n_eval), "after": _cap_ids(after_raw, n_eval)}
        else:
            dr = req["date_range"]
            cohorts_raw = {"all": _cap_ids(window_ids(dr["start"], dr["end"]), n_eval)}

    timer.log.info("Phase 0: raw cohort sizes %s", {k: len(v) for k, v in cohorts_raw.items()})

    features: dict[str, dict] = {}
    filtered: dict[str, list[str]] = {}

    def _process_session(sid: str) -> tuple[str, dict[str, Any]] | None:
        try:
            conv = load_or_fetch_conversation(store, sid)
            fv = compute_features(conv, include_embedding=False)
            if not _apply_traffic_split(fv, traffic_split):
                return None
            store.write_json(store.features_dir / f"{sid}.json", fv)
            if compiled and not passes_filters(fv, compiled):
                return None
            return sid, fv
        except Exception:
            return None

    for label, ids in cohorts_raw.items():
        with timer.track("0", "FeatureComputer", counts={"sessions_in": len(ids)}):
            results = run_parallel(
                ids, _process_session, max_workers=worker_count(),
                label=f"phase0-features-{label}",
            )
        kept = []
        for row in results:
            if not row:
                continue
            sid, fv = row
            features[sid] = fv
            kept.append(sid)
        filtered[label] = kept
        timer.log.info(
            "Phase 0: cohort %s — %d/%d sessions passed filters",
            label, len(kept), len(ids),
        )

    with timer.track("0", "OpeningEmbeddings"):
        n_embedded = apply_opening_embeddings(features)
        for sid, fv in features.items():
            store.write_json(store.features_dir / f"{sid}.json", fv)
        timer.log.info("Phase 0: embedded %d opening texts via OpenAI (parallel batches)", n_embedded)

    # Stratified n_eval subsample per cohort
    for label, ids in list(filtered.items()):
        cap = MAX_TRACE_SESSIONS if n_eval in (None, "all") else int(n_eval)
        if len(ids) > cap:
            items = [(sid, features[sid]) for sid in ids]
            filtered[label] = stratified_subsample(items, cap)
            timer.log.info("Phase 0: cohort %s subsampled to n_eval=%d", label, cap)

    with timer.track("0", "BlueprintFetcher"):
        bp_raw = fetch_blueprint(tenant, assistant_origin_id, channel)
        bp_summary = summarize_blueprint(bp_raw)
        store.write_json(store.intermediate_dir / "blueprint_summary.json", bp_summary)
        timer.log.info(
            "Phase 0: blueprint orchestration=%s skills=%d",
            bp_summary.get("orchestration_type"), len(bp_summary.get("skills") or []),
        )

    change_ctx = None
    if req.get("change_description") or req.get("pr_link"):
        timer.log.info("Phase 0: resolving change context (pr=%s)", bool(req.get("pr_link")))
        with timer.track("0", "ChangeContextResolver"):
            change_ctx = resolve_change_context(
                req.get("change_description") or "",
                req.get("pr_link"),
                bp_summary,
            )
            store.write_json(store.intermediate_dir / "change_context.json", change_ctx)

    all_ids = [sid for ids in filtered.values() for sid in ids]
    pilot = random.sample(all_ids, min(200, len(all_ids))) if all_ids else []
    with timer.track("0", "IntentLexiconBuilder"):
        lexicon = build_intent_lexicon(store, bp_summary, [features[s] for s in pilot if s in features])
        apply_intent_to_features(store, all_ids, lexicon)
        for sid in all_ids:
            if sid in features:
                features[sid] = store.read_json(store.features_dir / f"{sid}.json")

    stats = {
        "tenant": tenant,
        "assistant_origin_id": assistant_origin_id,
        "raw_counts": {k: len(v) for k, v in cohorts_raw.items()},
        "filtered_counts": {k: len(v) for k, v in filtered.items()},
        "session_ids": filtered,
        "n_explore": int(req.get("n_explore") or 100),
    }
    store.write_json(store.intermediate_dir / "cohort_stats.json", stats)
    timer.log.info(
        "Phase 0 complete — filtered_counts=%s explore_pool=%d",
        stats["filtered_counts"], len(all_ids),
    )
    return {"stats": stats, "features": features, "blueprint": bp_summary, "change_context": change_ctx}


def phase1_sample(store: StudyStore, stats: dict, req: dict, features: dict[str, dict], timer: StudyTimer) -> dict[str, Any]:
    timer.log.info("Phase 1: exploration sampling n_explore=%s", req.get("n_explore"))
    with timer.track("1", "ExplorationSampler"):
        manifest = build_exploration_manifest(
            req["study_type"],
            stats["session_ids"],
            features,
            int(req.get("n_explore") or 100),
            int(req.get("pairing_turn_tolerance") or 3),
        )
    store.write_json(store.intermediate_dir / "s_explore" / "manifest.json", manifest)
    timer.log.info("Phase 1 complete — %d exploration sessions selected", len(manifest.get("session_ids") or []))
    return manifest


def phase2a_digests(store: StudyStore, manifest: dict, timer: StudyTimer) -> None:
    n = len(manifest.get("session_ids") or [])
    timer.log.info("Phase 2a: building digests for %d sessions", n)
    with timer.track("2a", "DigestBuilder"):
        build_digests_parallel(store, manifest)


def phase2b_plan(store: StudyStore, req: dict, manifest: dict, stats: dict, timer: StudyTimer) -> dict[str, Any]:
    timer.log.info("Phase 2b: synthesizing analysis plan from %d digests", len(manifest.get("session_ids") or []))
    digests = []
    for sid in manifest["session_ids"][: min(20, len(manifest["session_ids"]))]:
        p = store.intermediate_dir / "s_explore" / f"{sid}.digest.json"
        if p.exists():
            digests.append(store.read_json(p))
    full_transcripts = pick_full_transcripts_for_plan(store, manifest["session_ids"])
    bp = store.read_json(store.intermediate_dir / "blueprint_summary.json")
    change = store.read_json(store.intermediate_dir / "change_context.json") if (store.intermediate_dir / "change_context.json").exists() else {}
    templates = load_artifact_templates()
    allowed_plots = list((templates.get("plots") or {}).keys())
    allowed_tables = list((templates.get("tables") or {}).keys())

    samples_text = []
    for d in digests[:12]:
        samples_text.append(f"Session {d['session_id']} [{d.get('cohort_label')}]: " + " | ".join(d.get("notable_events") or d.get("bullets") or []))
        for line in (d.get("transcript_digest") or [])[:4]:
            samples_text.append(f"  {line.get('speaker')}: {(line.get('text') or '')[:200]}")

    for ft in full_transcripts:
        samples_text.append(f"FULL TRANSCRIPT {ft['session_id']} turns={ft.get('turn_count')} anomalies={ft.get('anomaly_flags')}")
        for line in (ft.get("transcript") or [])[:12]:
            samples_text.append(f"  {line.get('speaker')}: {(line.get('text') or '')[:200]}")

    base_prompt = f"""You are Ypervaíno PlanSynthesizer. Return AnalysisPlan JSON.

Change context: {json.dumps(change, default=str)[:3000]}
Study type: {req.get('study_type')}
Cohort sizes: {json.dumps(stats.get('filtered_counts', {}))}
Blueprint: {bp.get('orchestration_type')} skills={[s.get('name') for s in (bp.get('skills') or [])[:12]]}

Samples:
{chr(10).join(samples_text[:60])}

Allowed plot templates: {allowed_plots}
Allowed table templates: {allowed_tables}

Required keys:
- exploration_summary
- quantitative.aspects[] with id,name,description,components[{{ref:{{kind, name}}, aggregation}}]
- quantitative.suggested_plots[] with template, aspect_id/title
- quantitative.suggested_tables[] with template
- qualitative.hypotheses[] with id,title,description,predicate (per-session only: e.g. "interruption_count >= 2 and transfer_count > 0" — NO mean()/rate()/when SQL)
- signals_required[] with method in rule_based|intent_classifier|embedding_nearest_neighbor (avoid zero_shot on full cohort)
- primitives_required[]
- user_approved:false
Use primitives: turn_count, main_stream_latency_p95, main_stream_estimated_cost_usd, tool_error_count, guardrail_triggered, opening_intent_class, session_outcome"""

    llm = LLMClient()
    plan = None
    last_errors: list[str] = []
    with timer.track("2b", "PlanSynthesizer", llm={"model": "gpt-4.1"}):
        for attempt in range(2):
            prompt = base_prompt if attempt == 0 else base_prompt + f"\n\nFix these validation errors:\n{last_errors}"
            timer.log.info("Phase 2b: PlanSynthesizer attempt %d/2", attempt + 1)
            plan = llm.json_completion(prompt, model="gpt-4.1", max_tokens=6000)
            last_errors = validate_plan(plan)
            if not last_errors:
                break
            timer.log.warning("Phase 2b: plan validation errors: %s", last_errors)
        if last_errors:
            raise PlanValidationError(last_errors)

    plan.setdefault("schema_version", "1.0")
    plan["user_approved"] = False
    plan["study_query"] = req
    store.write_json(store.intermediate_dir / "analysis_plan.json", plan)
    timer.log.info(
        "Phase 2b complete — aspects=%d hypotheses=%d",
        len((plan.get("quantitative") or {}).get("aspects") or []),
        len((plan.get("qualitative") or {}).get("hypotheses") or []),
    )
    return plan


def phase3_evaluate(store: StudyStore, req: dict, stats: dict, plan: dict, timer: StudyTimer) -> dict[str, Any]:
    n_sessions = sum(len(v) for v in stats.get("session_ids", {}).values())
    timer.log.info("Phase 3: evaluating %d sessions", n_sessions)
    with timer.track("3", "SignalExecutor"):
        eval_out = run_evaluation(plan, stats["session_ids"], store, req, load_or_fetch_conversation)
    for sid, row in eval_out["per_conversation"].items():
        store.write_json(store.output_dir / "per_conversation" / f"{sid}.json", row)

    narrative = ""
    with timer.track("3", "NarrativeSummarizer", llm={"model": "gpt-4.1-mini"}):
        try:
            narrative = LLMClient().json_completion(
                f"Summarize evaluation results as JSON {{summary, recommendations[]}}:\n{json.dumps({'aspects': eval_out['aspects'], 'hypotheses': eval_out['hypotheses']}, default=str)[:12000]}",
                model="gpt-4.1-mini",
                max_tokens=800,
            )
        except Exception:
            narrative = {"summary": "Evaluation complete.", "recommendations": []}

    is_comparative = req["study_type"] == "comparative"
    result = {
        "schema_version": "1.0",
        "study_type": req["study_type"],
        "cohort_sizes": {
            "before": len(stats["session_ids"].get("before") or []),
            "after": len(stats["session_ids"].get("after") or []),
            "total": sum(len(v) for v in stats["session_ids"].values()),
        },
        "quantitative": {"aspects": eval_out["aspects"]},
        "qualitative": {"hypotheses": eval_out["hypotheses"]},
        "aspects": eval_out["aspects"],
        "hypotheses": eval_out["hypotheses"],
        "artifacts": {
            "narrative_summary": narrative.get("summary") if isinstance(narrative, dict) else str(narrative),
            "recommendations": narrative.get("recommendations", []) if isinstance(narrative, dict) else [],
        },
        "exploration_summary": plan.get("exploration_summary") or "",
    }
    with timer.track("3", "ArtifactRenderer"):
        result["artifacts"]["tables"] = render_tables(store.output_dir, result, is_comparative)
        result["artifacts"]["plots"] = render_plots(store.output_dir, result, plan, is_comparative)
    store.write_json(store.output_dir / "evaluation_result.json", result)
    timer.log.info(
        "Phase 3 complete — aspects=%d hypotheses=%d artifacts=%d tables %d plots",
        len(result.get("aspects") or []),
        len(result.get("hypotheses") or []),
        len((result.get("artifacts") or {}).get("tables") or []),
        len((result.get("artifacts") or {}).get("plots") or []),
    )
    return result
