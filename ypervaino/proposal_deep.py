from __future__ import annotations

import json
import os
from typing import Any

from ypervaino.bot_repo import checkout_for_change, grep_repo, read_repo_file
from ypervaino.llm_client import LLMClient
from ypervaino.log import get_logger
from ypervaino.proposal_context import load_event_schema_excerpt
from ypervaino.proposal_prompts import DEEP_SYSTEM
from ypervaino.proposal_validate import normalize_evidence_list

_log = get_logger("proposal_deep")

PATTERNS = [
    "session_outcome",
    "transfer_count",
    "CALL_TRANSFER",
    "payment_failed",
    "FeatureComputer",
    "opening_intent",
]


def _normalize_deep_proposal(raw: dict[str, Any]) -> dict[str, Any]:
    p = dict(raw)
    p["evidence"] = normalize_evidence_list(p.get("evidence"))
    p.setdefault("status", "pending")
    p.setdefault("repo_references", p.get("repo_references") or [])
    if not p.get("category"):
        p["category"] = "other"
    return p


def fetch_repo_snippets(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    pr_link = (ctx.get("study_query") or {}).get("pr_link")
    snippets: list[dict[str, Any]] = []
    try:
        checkout_for_change(pr_link)
    except Exception as e:
        _log.debug("repo checkout failed: %s", e)
        return snippets
    for pattern in PATTERNS:
        try:
            result = grep_repo(pattern, paths=[], skip_checkout=True)
            for m in (result.get("matches") or [])[:5]:
                snippets.append({"pattern": pattern, **m})
        except Exception as e:
            _log.debug("grep %s failed: %s", pattern, e)
    for path in ["ypervaino/features.py", "ypervaino/evaluation.py"]:
        try:
            result = read_repo_file(path, skip_checkout=True)
            if result.get("content"):
                snippets.append({"path": path, "snippet": result["content"][:8000]})
        except Exception:
            pass
    return snippets[:30]


def generate_deep_proposals(ctx: dict[str, Any], snippets: list[dict[str, Any]], shallow_titles: list[str]) -> list[dict[str, Any]]:
    model = os.environ.get("PROPOSAL_DEEP_MODEL", "gpt-4.1")
    prompt = f"""{DEEP_SYSTEM}

## Task
Generate deep_proposals[] for issues that CANNOT be fixed via VA Blueprint edits alone.
Prioritize poor aspect metrics or failed/rejected hypotheses where blueprint edits are insufficient.

## Aspect results
{json.dumps(ctx.get("aspect_results") or [], default=str)[:60000]}

## Hypothesis results
{json.dumps(ctx.get("hypothesis_results") or [], default=str)[:60000]}

## Recommendations from Phase 3
{json.dumps(ctx.get("recommendations") or [], default=str)}

## Change context
{json.dumps(ctx.get("change_context") or {}, default=str)[:20000]}

## Event schema
{load_event_schema_excerpt(ctx.get("event_schema") or {})}

## Repo snippets (grep results)
{json.dumps(snippets, default=str)[:40000]}

## Shallow proposals already generated (do NOT duplicate these fixes)
{json.dumps(shallow_titles, default=str)}
"""
    _log.info("Call B deep proposals model=%s", model)
    data = LLMClient().json_completion(prompt, model=model, max_tokens=8000)
    proposals = data.get("deep_proposals") or data.get("proposals") or []
    if not isinstance(proposals, list):
        return []
    proposals = [_normalize_deep_proposal(p) for p in proposals if isinstance(p, dict)]
    _log.info("Call B parsed %d deep proposals", len(proposals))
    return proposals
