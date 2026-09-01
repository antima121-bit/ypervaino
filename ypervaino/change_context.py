from __future__ import annotations

import json
from typing import Any

from ypervaino.bot_repo import (
    BotRepoError,
    checkout_for_change,
    grep_repo,
    read_repo_file,
)
from ypervaino.llm_client import LLMClient
from ypervaino.log import get_logger

_log = get_logger("change_context")


def resolve_change_context(
    change_description: str,
    pr_link: str | None,
    blueprint_summary: dict[str, Any],
) -> dict[str, Any]:
    if not change_description and not pr_link:
        return {}

    _log.info("resolving change context pr_link=%r desc_len=%d", pr_link, len(change_description or ""))
    repo_meta: dict[str, Any] = {}
    try:
        repo_meta = checkout_for_change(pr_link)
    except BotRepoError as e:
        _log.warning("repo checkout failed: %s", e)
        repo_meta = {"checkout_error": str(e)}

    tools_desc = """
You are ChangeContextResolver. Respond with JSON only.
Tools (respond {{"tool": "<name>", "args": {{...}}}} or {{"tool":"finish","args":{{...}}}}):
- fetch_mr_metadata(url) — already in context if MR link given
- fetch_pr_diff(url) — use repo checkout + changed files summary from context
- read_repo_file(path) — read file from bot repo (e.g. llm_config.md, .context/README.md)
- grep_repo(pattern, paths[]) — search bot repo via git grep
- finish(change_context) — summary, affected_modules[], affected_purposes[], affected_event_types[]
Max 5 steps.
"""
    context_notes: list[Any] = [repo_meta]
    if pr_link:
        context_notes.append({"pr_link": pr_link, "note": "Repo checked out to MR source branch or PR head when available."})

    llm = LLMClient()
    change_ctx: dict[str, Any] | None = None
    transcript = (
        f"{tools_desc}\n"
        f"Change description: {change_description}\n"
        f"PR link: {pr_link or 'none'}\n"
        f"Blueprint: {json.dumps(blueprint_summary, default=str)[:4000]}\n"
        f"Repo checkout: {json.dumps(repo_meta, default=str)[:2000]}\n"
        "Step 1:"
    )

    for step_i in range(5):
        step = llm.json_completion(transcript, model="gpt-4.1", max_tokens=1500)
        tool = step.get("tool") or ("finish" if step.get("summary") else None)
        args = step.get("args") or step
        _log.info("step %d tool=%s args=%s", step_i + 1, tool, list((args or {}).keys()) if isinstance(args, dict) else type(args).__name__)

        if tool == "finish" or (not tool and args.get("summary")):
            change_ctx = {
                "summary": args.get("summary") or change_description,
                "affected_modules": args.get("affected_modules") or [],
                "affected_purposes": args.get("affected_purposes") or ["main_stream"],
                "affected_event_types": args.get("affected_event_types") or [],
                "repo_checkout": repo_meta,
            }
            break

        result: dict[str, Any]
        if tool == "fetch_mr_metadata":
            result = repo_meta if repo_meta.get("source_branch") else {"url": args.get("url") or pr_link, "note": "see repo_checkout"}
        elif tool == "fetch_pr_diff":
            branch = repo_meta.get("source_branch") or repo_meta.get("checked_out") or "development"
            diff = grep_repo(args.get("pattern") or "main_stream|llm|model", ["."]) if not args.get("url") else {}
            result = {"summary": change_description, "source_branch": branch, "grep_sample": diff.get("matches", [])[:20]}
        elif tool == "read_repo_file" and args.get("path"):
            try:
                result = read_repo_file(str(args["path"]), pr_link=pr_link)
            except BotRepoError as e:
                result = {"error": str(e), "path": args.get("path")}
        elif tool == "grep_repo" and args.get("pattern"):
            try:
                result = grep_repo(str(args["pattern"]), args.get("paths") or ["."], pr_link=pr_link)
            except BotRepoError as e:
                result = {"error": str(e), "pattern": args.get("pattern")}
        else:
            result = {"error": f"Unknown or malformed tool call: {tool}"}

        _log.debug("step %d result keys=%s", step_i + 1, list(result.keys()) if isinstance(result, dict) else type(result).__name__)
        context_notes.append(result)
        transcript = (
            f"{tools_desc}\n"
            f"Change description: {change_description}\n"
            f"PR link: {pr_link or 'none'}\n"
            f"Prior notes: {json.dumps(context_notes, default=str)[:8000]}\n"
            f"Step {step_i + 2}:"
        )

    if change_ctx is None:
        prompt = f"""Summarize this bot change for analysis planning.
Change: {change_description}
PR: {pr_link or 'none'}
Repo checkout: {json.dumps(repo_meta, default=str)[:4000]}
Notes: {json.dumps(context_notes, default=str)[:8000]}
Blueprint orchestration: {blueprint_summary.get('orchestration_type')}
Return JSON with summary, affected_modules[], affected_purposes[], affected_event_types[]"""
        change_ctx = llm.json_completion(prompt, model="gpt-4.1", max_tokens=1200)
        change_ctx.setdefault("affected_purposes", ["main_stream"])
        change_ctx["repo_checkout"] = repo_meta

    if pr_link:
        change_ctx["pr_link"] = pr_link
    _log.info("change context resolved summary_len=%d modules=%d", len(change_ctx.get("summary") or ""), len(change_ctx.get("affected_modules") or []))
    return change_ctx
