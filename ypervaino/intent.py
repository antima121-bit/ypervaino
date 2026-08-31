from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any

from ypervaino.config_loader import load_event_schema
from ypervaino.llm_client import LLMClient
from ypervaino.parallel import run_parallel, worker_count
from ypervaino.study_store import StudyStore

MIN_INTENT_SCORE = 2.0


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_")


def _structured_sets(fv: dict[str, Any]) -> dict[str, set[str]]:
    hits = fv.get("structured_hits") or {}
    return {
        "skills": {_norm(x) for x in hits.get("skills") or []},
        "tools": {_norm(x) for x in hits.get("tools") or []},
        "agents": {_norm(x) for x in hits.get("agent_names") or []},
        "nodes": {_norm(x) for x in hits.get("nodes") or []},
        "purposes": {_norm(x) for x in hits.get("purposes") or []},
        "event_types": {_norm(x) for x in hits.get("event_types") or []},
    }


def build_intent_lexicon(
    store: StudyStore,
    blueprint: dict[str, Any],
    pilot_features: list[dict[str, Any]],
) -> dict[str, Any]:
    cache = store.cache_dir / "intent_lexicon.json"
    if cache.exists():
        return store.read_json(cache)

    pilot_stats = Counter()
    for fv in pilot_features[:200]:
        for tool in (fv.get("structured_hits") or {}).get("tools") or []:
            pilot_stats[f"tool:{tool}"] += 1
        for sk in (fv.get("structured_hits") or {}).get("skills") or []:
            pilot_stats[f"skill:{sk}"] += 1

    schema = load_event_schema()
    etypes = schema.get("event_types") or {}
    if isinstance(etypes, dict):
        etype_names = list(etypes.keys())[:25]
    else:
        etype_names = list(etypes)[:25]

    prompt = """Build an IntentLexicon JSON for a voice bot study.
Blueprint skills: """ + json.dumps(blueprint.get('skills') or [])[:2000] + """
Tool catalog: """ + json.dumps(blueprint.get('tool_catalog') or [])[:2000] + """
Pilot frequent names: """ + str(pilot_stats.most_common(30)) + """
Event types sample: """ + json.dumps(etype_names, default=str) + """

Return JSON with keys version and intents (map of intent_id to label, description, skills, tools, agent_names, nodes, event_type_hints, keywords, purposes, negative_keywords).
Include mutually exclusive intents classifiable from logs, plus explicit unknown intent with empty matchers."""

    lexicon = LLMClient().json_completion(prompt, model="gpt-4.1-mini", max_tokens=4000)
    lexicon.setdefault("version", "1.0")
    if "unknown" not in (lexicon.get("intents") or {}):
        lexicon.setdefault("intents", {})["unknown"] = {
            "label": "unknown",
            "description": "No confident intent match",
            "skills": [], "tools": [], "agent_names": [], "nodes": [],
            "event_type_hints": [], "keywords": [], "purposes": [], "negative_keywords": [],
        }
    store.write_json(cache, lexicon)
    return lexicon


def classify_opening_intent(
    fv: dict[str, Any],
    lexicon: dict[str, Any],
) -> tuple[str, float]:
    intents = lexicon.get("intents") or {}
    text = (fv.get("searchable_text") or "").lower()
    opening = text[:800]
    structured = _structured_sets(fv)

    best_id, best_score = "unknown", 0.0
    pos_total = 0.0

    for intent_id, spec in intents.items():
        if intent_id == "unknown":
            continue
        score = 0.0
        for sk in spec.get("skills") or []:
            if _norm(sk) in structured["skills"]:
                score += 3.0
        for tool in spec.get("tools") or []:
            if _norm(tool) in structured["tools"]:
                score += 3.0
        for agent in spec.get("agent_names") or []:
            n = _norm(agent)
            if n in structured["agents"] or n in text:
                score += 2.5
        for node in spec.get("nodes") or []:
            if _norm(node) in structured["nodes"]:
                score += 2.5
        for purpose in spec.get("purposes") or []:
            if _norm(purpose) in structured["purposes"]:
                score += 2.0
        for et in spec.get("event_type_hints") or []:
            if _norm(et) in structured["event_types"]:
                score += 1.5
        for kw in spec.get("keywords") or []:
            k = (kw or "").lower()
            if k and k in text:
                score += 1.0
                if k in opening:
                    score += 0.5
        for nk in spec.get("negative_keywords") or []:
            if (nk or "").lower() in text:
                score -= 2.0

        if score > 0:
            pos_total += score
        if score > best_score:
            best_id, best_score = intent_id, score

    confidence = (best_score / pos_total) if pos_total > 0 else 0.0
    if best_score < MIN_INTENT_SCORE:
        return "unknown", confidence
    return best_id, round(confidence, 4)


def apply_intent_to_features(store: StudyStore, session_ids: list[str], lexicon: dict[str, Any]) -> None:
    def _one(sid: str) -> None:
        path = store.features_dir / f"{sid}.json"
        if not path.exists():
            return
        fv = store.read_json(path)
        intent, score = classify_opening_intent(fv, lexicon)
        fv["opening_intent_class"] = intent
        fv["opening_intent_score"] = score
        store.write_json(path, fv)

    run_parallel(session_ids, _one, max_workers=worker_count(), label="intent-scoring")
