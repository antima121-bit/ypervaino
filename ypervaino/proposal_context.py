from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ypervaino.blueprint_store import current_version, ensure_baseline, load_blueprint, load_dialog_flow
from ypervaino.settings import CONFIG_DIR
from ypervaino.study_store import StudyStore


def _aspects(evaluation: dict[str, Any]) -> list[dict[str, Any]]:
    q = evaluation.get("quantitative") or {}
    return evaluation.get("aspects") or q.get("aspects") or []


def _hypotheses(evaluation: dict[str, Any]) -> list[dict[str, Any]]:
    q = evaluation.get("qualitative") or {}
    return evaluation.get("hypotheses") or q.get("hypotheses") or []


def load_generation_context(store: StudyStore) -> dict[str, Any]:
    req = store.read_json(store.input_dir / "create_study.json")
    ensure_baseline(store, req)

    evaluation = store.read_json(store.output_dir / "evaluation_result.json")
    plan_path = store.intermediate_dir / "analysis_plan.json"
    analysis_plan = store.read_json(plan_path) if plan_path.exists() else {}

    change_path = store.intermediate_dir / "change_context.json"
    change_context = store.read_json(change_path) if change_path.exists() else {}

    event_schema: dict[str, Any] = {}
    es_path = CONFIG_DIR / "event_schema.json"
    if es_path.exists():
        event_schema = json.loads(es_path.read_text())

    artifacts = evaluation.get("artifacts") or {}
    recommendations = artifacts.get("recommendations") or []

    return {
        "study_slug": store.slug,
        "study_query": req,
        "evaluation": evaluation,
        "aspect_results": _aspects(evaluation),
        "hypothesis_results": _hypotheses(evaluation),
        "recommendations": recommendations,
        "analysis_plan": analysis_plan,
        "blueprint": load_blueprint(store),
        "dialog_flow": load_dialog_flow(store),
        "change_context": change_context,
        "event_schema": event_schema,
        "blueprint_current_version": current_version(store),
    }


def load_event_schema_excerpt(schema: dict[str, Any], limit: int = 12000) -> str:
    text = json.dumps(schema, default=str)
    return text[:limit]
