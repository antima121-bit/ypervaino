from __future__ import annotations

import json
import os
from typing import Any

from ypervaino.llm_client import LLMClient
from ypervaino.log import get_logger
from ypervaino.proposal_prompts import SHALLOW_SYSTEM
from ypervaino.proposal_validate import normalize_shallow_proposal

_log = get_logger("proposal_shallow")


def _skill_names(blueprint: dict[str, Any]) -> list[str]:
    skills = (blueprint.get("assistant_info") or {}).get("skill_list") or []
    return [s.get("name") for s in skills if s.get("name")][:20]


def generate_shallow_proposals(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    model = os.environ.get("PROPOSAL_SHALLOW_MODEL", "gpt-5.6")
    blueprint = ctx.get("blueprint") or {}
    skill_hint = _skill_names(blueprint)

    prompt = f"""{SHALLOW_SYSTEM}

## Task
Generate shallow_proposals[] addressing the worst findings across aspects and hypotheses below.
Use real skill/tool names from the blueprint. Copy anchor/find strings verbatim from instruction text.

Available skill names (use these in target.skill_name): {json.dumps(skill_hint)}

## Aspect results
{json.dumps(ctx.get("aspect_results") or [], default=str)[:60000]}

## Hypothesis results
{json.dumps(ctx.get("hypothesis_results") or [], default=str)[:60000]}

## Recommendations from Phase 3
{json.dumps(ctx.get("recommendations") or [], default=str)}

## Current VA Blueprint (full)
{json.dumps(blueprint, default=str)[:120000]}

## Dialog flow (if present)
{json.dumps(ctx.get("dialog_flow") or {}, default=str)[:40000]}

## Analysis plan
{json.dumps({
    "aspects": (ctx.get("analysis_plan") or {}).get("quantitative", {}).get("aspects"),
    "hypotheses": (ctx.get("analysis_plan") or {}).get("qualitative", {}).get("hypotheses"),
}, default=str)[:30000]}
"""
    _log.info("Call A shallow proposals model=%s", model)
    data = LLMClient().json_completion(prompt, model=model, schema_name="shallow_proposals_response")
    proposals = data.get("shallow_proposals") or data.get("proposals") or []
    if not isinstance(proposals, list):
        return []
    proposals = [normalize_shallow_proposal(p) for p in proposals if isinstance(p, dict)]
    _log.info("Call A parsed %d shallow proposals", len(proposals))
    return proposals
