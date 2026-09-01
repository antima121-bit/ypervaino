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
LEXICON_VERSION = "2.1"

# LLM event_value.purpose tags (log vocabulary — not caller-facing descriptions).
STANDARD_LOG_PURPOSES = frozenset({
    "main_stream",
    "contextual_query",
    "router",
    "input_guardrail",
    "closing_msg",
    "system_variables",
    "custom_variables",
})

# Keyword hits weighted by caller turn index: turn 1 → 1×, turn 2 → ½×, turn 3 → ⅓×, …
KEYWORD_BASE_WEIGHT = 3.0
NEGATIVE_KEYWORD_BASE_WEIGHT = 2.0
ROUTING_SKILL_WEIGHT = 1.0
ROUTING_TOOL_WEIGHT = 0.75


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


def _turn_weight(turn_index: int) -> float:
    """1-indexed turn index → 1, 1/2, 1/3, …"""
    return 1.0 / turn_index


def _user_turns(fv: dict[str, Any]) -> list[str]:
    turns = fv.get("user_turns")
    if turns:
        return [str(t).lower() for t in turns if str(t).strip()]
    # Back-compat for feature vectors cached before user_turns existed.
    text = (fv.get("user_searchable_text") or "").strip()
    if text:
        return [line.strip().lower() for line in text.split("\n") if line.strip()]
    opening = (fv.get("opening_text") or "").strip().lower()
    return [opening] if opening else []


def _caller_text(fv: dict[str, Any]) -> str:
    return "\n".join(_user_turns(fv))


def _pilot_caller_samples(pilot_features: list[dict[str, Any]]) -> dict[str, Any]:
    openings: list[str] = []
    user_snippets: list[str] = []
    phrase_counts: Counter[str] = Counter()

    for fv in pilot_features[:200]:
        opening = (fv.get("opening_text") or "").strip()
        if opening:
            openings.append(opening)
        turns = _user_turns(fv)
        if turns:
            user_snippets.append(" ".join(turns)[:240])
            for phrase in turns:
                phrase = phrase.strip()
                if len(phrase.split()) >= 2:
                    phrase_counts[phrase[:120]] += 1
        else:
            user_text = (fv.get("user_searchable_text") or "").strip()
            if user_text:
                user_snippets.append(user_text[:240])

    return {
        "opening_utterances": openings[:40],
        "caller_snippets": user_snippets[:20],
        "frequent_caller_phrases": phrase_counts.most_common(25),
    }


def _pilot_log_purposes(
    pilot_features: list[dict[str, Any]],
) -> tuple[list[tuple[str, int]], set[str]]:
    counts: Counter[str] = Counter()
    for fv in pilot_features[:200]:
        for purpose in (fv.get("structured_hits") or {}).get("purposes") or []:
            name = str(purpose).strip()
            if name:
                counts[name] += 1
    allowed = set(counts.keys()) | set(STANDARD_LOG_PURPOSES)
    return counts.most_common(30), allowed


def _normalize_lexicon(
    lexicon: dict[str, Any],
    *,
    allowed_purposes: set[str] | None = None,
) -> dict[str, Any]:
    intents = dict(lexicon.get("intents") or {})
    allowed_purpose_norm = {_norm(p) for p in (allowed_purposes or STANDARD_LOG_PURPOSES)}
    if "unknown" not in intents:
        intents["unknown"] = {
            "label": "Unknown",
            "description": "No confident caller-intent match",
            "skills": [], "tools": [], "agent_names": [], "nodes": [],
            "event_type_hints": [], "keywords": [], "purposes": [], "negative_keywords": [],
        }
    # Drop duplicate fallback bucket if the LLM also emitted Unknown/UNKNOWN.
    for dup in ("Unknown", "UNKNOWN"):
        if dup in intents and dup != "unknown":
            del intents[dup]

    cleaned: dict[str, Any] = {}
    for intent_id, spec in intents.items():
        if not isinstance(spec, dict):
            continue
        entry = dict(spec)
        for field in (
            "skills", "tools", "agent_names", "nodes",
            "event_type_hints", "keywords", "negative_keywords",
        ):
            vals = entry.get(field) or []
            entry[field] = [
                str(v).strip()
                for v in vals
                if v and str(v).strip() and not str(v).startswith("tool:")
            ]
        purpose_vals = entry.get("purposes") or []
        entry["purposes"] = [
            str(v).strip()
            for v in purpose_vals
            if v and str(v).strip() and _norm(str(v)) in allowed_purpose_norm
        ]
        cleaned[intent_id] = entry

    lexicon["intents"] = cleaned
    lexicon["version"] = LEXICON_VERSION
    return lexicon


def build_intent_lexicon(
    store: StudyStore,
    blueprint: dict[str, Any],
    pilot_features: list[dict[str, Any]],
) -> dict[str, Any]:
    cache = store.cache_dir / "intent_lexicon.json"
    if cache.exists():
        cached = store.read_json(cache)
        if cached.get("version") == LEXICON_VERSION:
            return cached

    pilot_stats = Counter()
    for fv in pilot_features[:200]:
        for tool in (fv.get("structured_hits") or {}).get("tools") or []:
            pilot_stats[f"tool:{tool}"] += 1
        for sk in (fv.get("structured_hits") or {}).get("skills") or []:
            pilot_stats[f"skill:{sk}"] += 1

    caller_samples = _pilot_caller_samples(pilot_features)
    purpose_stats, allowed_purposes = _pilot_log_purposes(pilot_features)
    schema = load_event_schema()
    etypes = schema.get("event_types") or {}
    if isinstance(etypes, dict):
        etype_names = list(etypes.keys())[:25]
    else:
        etype_names = list(etypes)[:25]

    skill_routing = [
        {
            "skill": s.get("name"),
            "tools": s.get("tools") or [],
            "trigger_hint": (s.get("trigger_hint") or "")[:200],
        }
        for s in (blueprint.get("skills") or [])
    ]

    prompt = """Build an IntentLexicon JSON for a voice-bot study.

GOAL
Define what the CALLER wants — not bot skill names, tool ids, debug events, or internal routing labels.

RULES
1. intent_id and label must describe caller goals in plain language (snake_case ids), e.g. pay_bill, billing_question, verify_identity, speak_to_agent, add_payment_method.
2. Do NOT use blueprint skill names (Billing_Queries, Main_Auth, etc.) as intent_id or label.
3. keywords must come from real caller language (Spanish and/or English). Mine them from the pilot samples below.
4. skills[], tools[], nodes[] are optional ROUTING HINTS only — map which bot modules often handle each caller intent after routing.
5. purposes[] must be LOG LLM purpose tags (event_value.purpose), NOT business descriptions.
   - ONLY use values from "Observed log purposes" or the standard set: """ + json.dumps(sorted(STANDARD_LOG_PURPOSES)) + """
   - NEVER invent prose like "process payment", "stop payment process", or "cancel transaction".
   - Caller-facing phrases about stopping/canceling belong in keywords[] or negative_keywords[], not purposes[].
6. Intents are mutually exclusive per conversation (one primary opening intent).
7. Include exactly one fallback intent with intent_id "unknown" and empty matchers.
8. negative_keywords should only rule out clear contradictions in CALLER text, not bot responses.
9. Prefer 5–10 specific caller intents plus unknown.

FIELD GUIDE
- keywords[]        → what the caller says (user utterances)
- purposes[]        → technical LLM purpose tags seen in logs (main_stream, contextual_query, …)
- skills[]/tools[]  → blueprint routing hints only

Pilot opening utterances:
""" + json.dumps(caller_samples.get("opening_utterances") or [], ensure_ascii=False)[:2500] + """

Pilot caller snippets (all user turns):
""" + json.dumps(caller_samples.get("caller_snippets") or [], ensure_ascii=False)[:2500] + """

Pilot frequent caller phrases:
""" + json.dumps(caller_samples.get("frequent_caller_phrases") or [], ensure_ascii=False)[:1500] + """

Observed log purposes (event_value.purpose frequency in pilot — purposes[] must be chosen from here):
""" + json.dumps(purpose_stats, ensure_ascii=False)[:1500] + """

Allowed purposes (union of observed + standard):
""" + json.dumps(sorted(allowed_purposes), ensure_ascii=False)[:1000] + """

Blueprint routing reference (for skills/tools mapping only):
""" + json.dumps(skill_routing, ensure_ascii=False)[:2500] + """

Tool catalog:
""" + json.dumps(blueprint.get("tool_catalog") or [], ensure_ascii=False)[:1500] + """

Pilot routing stats (secondary):
""" + str(pilot_stats.most_common(30)) + """

Event types sample:
""" + json.dumps(etype_names, default=str) + """

Return JSON with keys version and intents.
Each intent value must include: label, description, skills, tools, agent_names, nodes, event_type_hints, keywords, purposes, negative_keywords.
purposes[] values must exactly match allowed log purpose strings listed above."""

    lexicon = LLMClient().json_completion(prompt, model="gpt-4.1-mini", max_tokens=4000)
    lexicon = _normalize_lexicon(lexicon, allowed_purposes=allowed_purposes)
    store.write_json(cache, lexicon)
    return lexicon


def classify_opening_intent(
    fv: dict[str, Any],
    lexicon: dict[str, Any],
) -> tuple[str, float]:
    intents = lexicon.get("intents") or {}
    user_turns = _user_turns(fv)
    structured = _structured_sets(fv)

    best_id, best_score = "unknown", 0.0
    pos_total = 0.0

    for intent_id, spec in intents.items():
        if intent_id == "unknown":
            continue
        score = 0.0
        for sk in spec.get("skills") or []:
            if _norm(sk) in structured["skills"]:
                score += ROUTING_SKILL_WEIGHT
        for tool in spec.get("tools") or []:
            if _norm(tool) in structured["tools"]:
                score += ROUTING_TOOL_WEIGHT
        for agent in spec.get("agent_names") or []:
            if _norm(agent) in structured["agents"]:
                score += 1.0
        for node in spec.get("nodes") or []:
            if _norm(node) in structured["nodes"]:
                score += 1.0
        for purpose in spec.get("purposes") or []:
            if _norm(purpose) in structured["purposes"]:
                score += 0.75
        for et in spec.get("event_type_hints") or []:
            if _norm(et) in structured["event_types"]:
                score += 0.5
        for turn_idx, turn_text in enumerate(user_turns, start=1):
            turn_w = _turn_weight(turn_idx)
            for kw in spec.get("keywords") or []:
                k = (kw or "").lower().strip()
                if k and k in turn_text:
                    score += KEYWORD_BASE_WEIGHT * turn_w
            for nk in spec.get("negative_keywords") or []:
                nk_l = (nk or "").lower().strip()
                if nk_l and nk_l in turn_text:
                    score -= NEGATIVE_KEYWORD_BASE_WEIGHT * turn_w

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
