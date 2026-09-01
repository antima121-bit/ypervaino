from __future__ import annotations

import json
import math
import random
import statistics
from collections import defaultdict
from datetime import datetime
from typing import Any

from ypervaino.artifacts import render_tables
from ypervaino.config_loader import load_filter_atoms
from ypervaino.data_layer import (
    fetch_blueprint,
    fetch_session_id_list,
    fetch_trace,
    materialize_conversation,
    parse_dt,
    summarize_blueprint,
)
from ypervaino.features import compute_features
from ypervaino.llm_client import LLMClient
from ypervaino.settings import MAX_TRACE_SESSIONS
from ypervaino.study_store import StudyStore


def _apply_limit(ids: list[str], n_eval: Any) -> list[str]:
    if n_eval == "all" or n_eval is None:
        cap = MAX_TRACE_SESSIONS
    else:
        cap = int(n_eval)
    if len(ids) > cap:
        random.shuffle(ids)
        return ids[:cap]
    return ids


def load_or_fetch_conversation(store: StudyStore, session_uuid: str) -> dict[str, Any]:
    cache = store.traces_dir / f"{session_uuid}.json"
    if cache.exists():
        return store.read_json(cache)
    trace = fetch_trace(session_uuid)
    conv = materialize_conversation(session_uuid, trace)
    store.write_json(cache, conv)
    return conv


def compile_predicate(filters: list[dict]) -> list[dict]:
    atoms = {a["id"]: a for a in load_filter_atoms()}
    compiled = []
    for f in filters or []:
        atom = atoms.get(f.get("atom_id") or f.get("id"))
        if not atom:
            continue
        compiled.append({**atom, "user_value": f.get("value")})
    return compiled


def passes_filters(features: dict[str, Any], compiled: list[dict]) -> bool:
    for atom in compiled:
        prim = atom["primitive"]
        op = atom["op"]
        if prim == "agent_ever":
            name = (atom.get("user_value") or "").lower()
            if name and name not in (features.get("agent_path") or "").lower():
                return False
            continue
        val = features.get(prim)
        if atom.get("value") is not None:
            target = atom["value"]
        else:
            target = atom.get("user_value")
        if op == "==":
            if val != target:
                return False
        elif op == "!=":
            if val == target:
                return False
        elif op == ">=":
            if val is None or val < target:
                return False
        elif op == "<=":
            if val is None or val > target:
                return False
        elif op == ">":
            if val is None or val <= target:
                return False
        elif op == "in":
            if val not in (target or []):
                return False
    return True


def phase0_cohort(store: StudyStore, req: dict[str, Any]) -> dict[str, Any]:
    tenant = req["tenant"]
    assistant_origin_id = req["assistant_origin_id"]
    channel = req.get("channel") or "voice"
    n_eval = req.get("n_eval", "all")
    compiled = compile_predicate(req.get("cohort_filters") or [])

    def window_ids(start_s: str, end_s: str) -> list[str]:
        return fetch_session_id_list(
            tenant, assistant_origin_id, channel, parse_dt(start_s), parse_dt(end_s),
            assistant_id=req.get("assistant_id"),
            limit=None,
        )

    if req["study_type"] == "comparative":
        before_ids = _apply_limit(window_ids(req["date_range_before"]["start"], req["date_range_before"]["end"]), n_eval)
        after_ids = _apply_limit(window_ids(req["date_range_after"]["start"], req["date_range_after"]["end"]), n_eval)
        cohorts = {"before": before_ids, "after": after_ids}
    else:
        dr = req["date_range"]
        single = _apply_limit(window_ids(dr["start"], dr["end"]), n_eval)
        cohorts = {"all": single}

    features_by_cohort: dict[str, list[dict]] = {}
    filtered: dict[str, list[str]] = {}

    for label, ids in cohorts.items():
        feats = []
        kept = []
        for sid in ids:
            try:
                conv = load_or_fetch_conversation(store, sid)
                fv = compute_features(conv)
                store.write_json(store.features_dir / f"{sid}.json", fv)
                if compiled and not passes_filters(fv, compiled):
                    continue
                feats.append(fv)
                kept.append(sid)
            except Exception:
                continue
        features_by_cohort[label] = feats
        filtered[label] = kept

    bp_raw = fetch_blueprint(tenant, assistant_origin_id, channel)
    bp_summary = summarize_blueprint(bp_raw)
    store.write_json(store.intermediate_dir / "blueprint_summary.json", bp_summary)

    change_ctx = None
    if req.get("change_description") or req.get("pr_link"):
        change_ctx = {
            "summary": req.get("change_description") or "",
            "pr_link": req.get("pr_link"),
            "affected_purposes": ["main_stream"],
        }
        store.write_json(store.intermediate_dir / "change_context.json", change_ctx)

    stats = {
        "tenant": tenant,
        "assistant_origin_id": assistant_origin_id,
        "raw_counts": {k: len(v) for k, v in cohorts.items()},
        "filtered_counts": {k: len(v) for k, v in filtered.items()},
        "session_ids": filtered,
    }
    store.write_json(store.intermediate_dir / "cohort_stats.json", stats)
    return {"stats": stats, "features_by_cohort": features_by_cohort, "blueprint": bp_summary, "change_context": change_ctx}


def phase1_sample(stats: dict, n_explore: int, study_type: str) -> dict[str, Any]:
    if study_type == "comparative":
        before = stats["session_ids"].get("before") or []
        after = stats["session_ids"].get("after") or []
        n_each = max(1, n_explore // 2)
        random.shuffle(before)
        random.shuffle(after)
        sample = {"before": before[:n_each], "after": after[:n_each]}
    else:
        all_ids = stats["session_ids"].get("all") or []
        random.shuffle(all_ids)
        sample = {"all": all_ids[:n_explore]}
    flat = []
    for ids in sample.values():
        flat.extend(ids)
    return {"by_cohort": sample, "session_ids": flat}


def phase2a_digests(store: StudyStore, session_ids: list[str]) -> None:
    for sid in session_ids:
        conv = load_or_fetch_conversation(store, sid)
        fv = store.read_json(store.features_dir / f"{sid}.json") if (store.features_dir / f"{sid}.json").exists() else compute_features(conv)
        bullets = [
            f"turns={fv.get('turn_count')} outcome={fv.get('session_outcome')}",
            f"model={fv.get('main_stream_model')} latency_p95={fv.get('main_stream_latency_p95')}ms",
            f"tools={fv.get('tool_invocation_count')} guardrail={fv.get('guardrail_triggered')}",
        ]
        digest = {
            "session_id": sid,
            "transcript": conv.get("transcript") or [],
            "bullets": bullets,
            "primitive_snapshot": {k: fv[k] for k in (
                "turn_count", "main_stream_latency_p95", "main_stream_estimated_cost_usd",
                "tool_error_count", "guardrail_triggered", "opening_intent_class",
            ) if k in fv},
        }
        store.write_json(store.intermediate_dir / "s_explore" / f"{sid}.digest.json", digest)


def phase2b_plan(store: StudyStore, req: dict, manifest: dict, stats: dict) -> dict[str, Any]:
    digests = []
    for sid in manifest["session_ids"][: min(20, len(manifest["session_ids"]))]:
        p = store.intermediate_dir / "s_explore" / f"{sid}.digest.json"
        if p.exists():
            digests.append(store.read_json(p))

    bp = store.read_json(store.intermediate_dir / "blueprint_summary.json") if (store.intermediate_dir / "blueprint_summary.json").exists() else {}
    change = req.get("change_description") or "Pure discovery — no specific change described."

    samples_text = []
    for d in digests[:8]:
        samples_text.append(f"Session {d['session_id']}: " + " | ".join(d.get("bullets") or []))
        for line in (d.get("transcript") or [])[:4]:
            samples_text.append(f"  {line.get('speaker')}: {line.get('text', '')[:200]}")

    prompt = f"""You are Ypervaíno plan synthesizer. Create an analysis plan JSON for a voice bot study.

Change context: {change}
Study type: {req.get('study_type')}
Cohort sizes (filtered): {json.dumps(stats.get('filtered_counts', {}))}
Blueprint orchestration: {bp.get('orchestration_type')}
Skills: {[s.get('name') for s in (bp.get('skills') or [])[:10]]}

Sample digest lines:
{chr(10).join(samples_text[:40])}

Return JSON with keys:
- exploration_summary (string)
- quantitative.aspects: array of {{id, name, description, components:[{{ref:{{kind, name}}, aggregation}}]}}
  Use primitive names: turn_count, main_stream_latency_p95, main_stream_estimated_cost_usd, tool_error_count, guardrail_triggered
- quantitative.suggested_plots: array with template aspect_before_after_bar or aspect_single_cohort_bar
- quantitative.suggested_tables: array with template aspect_summary, hypothesis_summary
- qualitative.hypotheses: array of {{id, title, description, signals, predicate}}
  predicate uses op AND with cmp nodes: {{op:"cmp", name, cmp, value}}
  value MUST be a literal (number, boolean, or string) matching the primitive — never "before_mean"
  Examples: turn_count >= 5, guardrail_triggered == false, opening_intent_class == "billing"
  Include rule_based semantic signals in signals_required when using keyword signals
- primitives_required: array of {{kind:"primitive", name}}
- signals_required: array for rule_based signals
- user_approved: false
Keep 3-5 aspects and 2-4 hypotheses grounded in samples."""

    plan = LLMClient().json_completion(prompt, model="gpt-4.1-mini", max_tokens=5000)
    plan.setdefault("schema_version", "1.0")
    plan["user_approved"] = False
    plan["study_query"] = req
    store.write_json(store.intermediate_dir / "analysis_plan.json", plan)
    return plan


def _eval_predicate(node: Any, values: dict[str, Any]) -> bool:
    if not node:
        return True
    if isinstance(node, dict) and node.get("op") in ("AND", "and"):
        children = node.get("args") or node.get("nodes") or []
        return all(_eval_predicate(a, values) for a in children)
    if isinstance(node, dict) and node.get("op") in ("OR", "or"):
        children = node.get("args") or node.get("nodes") or []
        return any(_eval_predicate(a, values) for a in children)
    if isinstance(node, dict) and node.get("op") == "cmp":
        name = _resolve_field(node.get("name"), values) or node.get("name")
        val = values.get(name)
        cmp = node.get("cmp") or node.get("operator")
        target = node.get("value")
        if isinstance(target, str) and target in ("before_mean", "after_mean", "before_sum", "after_sum"):
            return False
        if cmp in ("=", "=="):
            return val == target
        if cmp == "!=":
            return val != target
        try:
            if isinstance(val, bool):
                val = 1.0 if val else 0.0
            if isinstance(target, bool):
                target = 1.0 if target else 0.0
            if not isinstance(val, (int, float)) or not isinstance(target, (int, float)):
                return False
            if cmp == ">":
                return val > target
            if cmp == ">=":
                return val >= target
            if cmp == "<":
                return val < target
            if cmp == "<=":
                return val <= target
        except TypeError:
            return False
    return False


def _rule_based_signal(spec: dict, fv: dict) -> Any:
    text = fv.get("searchable_text") or ""
    keywords = [k.lower() for k in (spec.get("keywords") or [])]
    hits = sum(1 for k in keywords if k in text)
    labels = spec.get("labels") or ["match"]
    return labels[0] if hits >= int(spec.get("min_hits") or 1) else (labels[-1] if len(labels) > 1 else "other")


# PlanSynthesizer's LLM very consistently reaches for these names instead of
# the real FeatureVector keys (confirmed by auditing every plan.json produced
# so far -- "outcome" instead of "session_outcome" alone appeared in ~20
# aspects/predicates across every study). Aliasing them is far cheaper and
# safer than hoping every future plan happens to use the exact schema name;
# the prompt should still be tightened separately, but this catches the
# common case immediately instead of silently returning "no data"/no-match.
FIELD_ALIASES = {
    "outcome": "session_outcome",
    "tools": "tool_invocation_count",
    "tools_used": "tool_invocation_count",
    "tool_usage_count": "tool_invocation_count",
}


def _resolve_field(name: str | None, fv: dict[str, Any]) -> str | None:
    if name in fv:
        return name
    alias = FIELD_ALIASES.get(name or "")
    return alias if alias in fv else None


def _aggregate(values: list[float], aggregation: str) -> float:
    if not values:
        return 0.0
    if aggregation == "sum":
        return float(sum(values))
    if aggregation == "max":
        return float(max(values))
    if aggregation == "min":
        return float(min(values))
    if aggregation == "count":
        # Count how many components were actually true/nonzero -- NOT how
        # many components exist. The latter always returns a constant equal
        # to len(values) regardless of the real values (e.g. a single boolean
        # primitive like guardrail_triggered always "counted" as 1, even when
        # every session's real value was False).
        return float(sum(1 for v in values if v))
    if aggregation in ("p95", "median"):
        if len(values) >= 2:
            if aggregation == "median":
                return float(statistics.median(values))
            return float(statistics.quantiles(values, n=20)[-1])
        return float(values[0])
    return float(statistics.mean(values))


def _aspect_value(aspect: dict, fv: dict[str, Any]) -> float | None:
    components = aspect.get("components") or []
    if not components:
        name = _resolve_field(aspect.get("id") or aspect.get("name"), fv)
        if name and isinstance(fv[name], (int, float)):
            return float(fv[name])
        return None
    vals = []
    for comp in components:
        ref = comp.get("ref") or {}
        prim = _resolve_field(ref.get("name"), fv)
        if prim is None:
            continue
        raw = fv[prim]
        if isinstance(raw, bool):
            raw = 1.0 if raw else 0.0
        if not isinstance(raw, (int, float)):
            continue
        vals.append(float(raw))
    if not vals:
        return None
    aggregation = (components[0].get("aggregation") or "mean").lower()
    return _aggregate(vals, aggregation)


def phase3_evaluate(store: StudyStore, req: dict, stats: dict, plan: dict) -> dict[str, Any]:
    min_support = int(req.get("min_support") or 30)
    is_comparative = req["study_type"] == "comparative"

    cohort_ids = stats["session_ids"]
    per_cohort_aspect: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    aspect_results = []
    hypothesis_results = []
    # PlanSynthesizer's LLM output isn't schema-validated before this runs
    # (architecture.md calls for that; not yet built) -- filter out any
    # malformed (non-dict) entries so one bad item doesn't crash the study.
    aspects = [a for a in ((plan.get("quantitative") or {}).get("aspects") or []) if isinstance(a, dict)]
    hypotheses = [h for h in ((plan.get("qualitative") or {}).get("hypotheses") or []) if isinstance(h, dict)]
    per_conversation: dict[str, dict] = {}

    for cohort_label, ids in cohort_ids.items():
        for sid in ids:
            fv_path = store.features_dir / f"{sid}.json"
            if not fv_path.exists():
                try:
                    conv = load_or_fetch_conversation(store, sid)
                    fv = compute_features(conv)
                    store.write_json(fv_path, fv)
                except Exception:
                    continue
            else:
                fv = store.read_json(fv_path)

            values = dict(fv)
            for sig in plan.get("signals_required") or []:
                # PlanSynthesizer's LLM output isn't schema-validated before
                # this runs (architecture.md calls for that, not yet built) --
                # seen in practice emitting plain strings instead of
                # {"method": ..., "name": ..., "spec": ...} dicts. Skip
                # anything malformed instead of crashing the whole study.
                if not isinstance(sig, dict):
                    continue
                if sig.get("method") == "rule_based" and sig.get("name"):
                    values[sig["name"]] = _rule_based_signal(sig.get("spec") or {}, fv)

            for aspect in aspects:
                av = _aspect_value(aspect, values)
                if av is not None:
                    key = aspect.get("id") or aspect.get("name")
                    per_cohort_aspect[cohort_label][key].append(av)

            hyp_matches = {}
            for hyp in hypotheses:
                hyp_matches[hyp.get("id")] = _eval_predicate(hyp.get("predicate"), values)
            per_conversation[sid] = {
                "session_id": sid,
                "cohort": cohort_label,
                "values": values,
                "hypotheses": hyp_matches,
            }

    for sid, row in per_conversation.items():
        store.write_json(store.output_dir / "per_conversation" / f"{sid}.json", row)

    for aspect in aspects:
        name = aspect.get("id") or aspect.get("name")
        if is_comparative:
            before_vals = per_cohort_aspect.get("before", {}).get(name) or []
            after_vals = per_cohort_aspect.get("after", {}).get(name) or []
            # An empty list here means _aspect_value never resolved for any
            # session -- usually the LLM referenced a primitive name that
            # doesn't exist in the FeatureVector schema (seen in practice:
            # "tools" instead of "tool_invocation_count"). That's "no data",
            # not "measured zero" -- defaulting to 0 silently shows a
            # confident-looking but fabricated number, so surface None/no_data
            # instead and let the UI say so.
            if not before_vals and not after_vals:
                aspect_results.append({
                    "id": name, "name": aspect.get("name") or name,
                    "before": None, "after": None, "delta_pct": None,
                    "good_if": "down", "no_data": True,
                })
                continue
            b = statistics.mean(before_vals) if before_vals else 0
            a = statistics.mean(after_vals) if after_vals else 0
            delta_pct = 0 if b == 0 else (a - b) / b * 100
            aspect_results.append({
                "id": name,
                "name": aspect.get("name") or name,
                "before": round(b, 3),
                "after": round(a, 3),
                "delta_pct": round(delta_pct, 1),
                "good_if": "down" if any(x in name for x in ("latency", "cost", "error")) else "up",
            })
        else:
            vals = per_cohort_aspect.get("all", {}).get(name) or []
            if not vals:
                # Same "no data" case as the comparative branch above --
                # _aspect_value never resolved (usually a nonexistent
                # primitive name from the LLM plan). Don't fake a 0.
                aspect_results.append({
                    "id": name, "name": aspect.get("name") or name,
                    "value": None, "before": None, "after": None,
                    "delta_pct": None, "good_if": "down", "no_data": True,
                })
                continue
            m = statistics.mean(vals)
            aspect_results.append({
                "id": name,
                "name": aspect.get("name") or name,
                "value": round(m, 3),
                # No real before/after split exists for a single-cohort study --
                # leave these null rather than duplicating `value` into both,
                # which used to render as a fake "0% change" comparison.
                "before": None,
                "after": None,
                "delta_pct": None,
                "good_if": "down",
            })

    for hyp in hypotheses:
        hid = hyp.get("id")
        rates = {}
        for cohort_label, ids in cohort_ids.items():
            matches = sum(
                1 for sid in ids
                if per_conversation.get(sid, {}).get("hypotheses", {}).get(hid)
            )
            rates[cohort_label] = {"support": matches, "rate": matches / len(ids) if ids else 0}
        hypothesis_results.append({
            "id": hid,
            "title": hyp.get("title"),
            "description": hyp.get("description"),
            "rates": rates,
            "rejected": sum(r["support"] for r in rates.values()) < min_support,
        })

    narrative = ""
    try:
        narrative = LLMClient().json_completion(
            f"Summarize these evaluation results in 3-4 sentences as JSON with key summary:\n{json.dumps({'aspects': aspect_results, 'hypotheses': hypothesis_results}, default=str)}",
            max_tokens=500,
        ).get("summary") or ""
    except Exception:
        narrative = "Evaluation complete."

    result = {
        "schema_version": "1.0",
        "study_type": req["study_type"],
        "is_comparative": is_comparative,
        "cohort_sizes": {
            # single_cohort studies store their ids under "all", not
            # "before"/"after" -- report the true count there instead of
            # silently showing 0/0 for a non-comparative study.
            "before": len(cohort_ids.get("before") or []) if is_comparative else None,
            "after": len(cohort_ids.get("after") or []) if is_comparative else None,
            "total": sum(len(v) for v in cohort_ids.values()),
        },
        "aspects": aspect_results,
        "hypotheses": hypothesis_results,
        "artifacts": {"narrative_summary": narrative},
        "exploration_summary": (plan.get("exploration_summary") or ""),
    }
    table_paths = render_tables(store.output_dir, result, is_comparative)
    result["artifacts"]["tables"] = table_paths
    store.write_json(store.output_dir / "evaluation_result.json", result)
    return result
