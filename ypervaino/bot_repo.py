from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ypervaino.settings import BOT_REPO_CACHE_DIR, BOT_REPO_DEFAULT_BRANCH, BOT_REPO_URL
from ypervaino.log import get_logger

_log = get_logger("bot_repo")


class BotRepoError(Exception):
    pass


def _run(cmd: list[str], cwd: Path) -> str:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise BotRepoError(proc.stderr.strip() or proc.stdout.strip() or f"Command failed: {' '.join(cmd)}")
    return proc.stdout


def _parse_gitlab_mr(url: str) -> tuple[str, int] | None:
    parsed = urlparse(url)
    if "gitlab.com" not in parsed.netloc:
        return None
    m = re.search(r"/merge_requests/(\d+)", parsed.path)
    if not m:
        return None
    parts = [p for p in parsed.path.split("/") if p and p != "-"]
    if len(parts) < 2:
        return None
    project_path = "/".join(parts[:2])
    return project_path, int(m.group(1))


def _fetch_gitlab_mr_branches(project_path: str, iid: int) -> dict[str, str]:
    token = os.environ.get("GITLAB_TOKEN") or os.environ.get("GITLAB_PRIVATE_TOKEN")
    headers = {"PRIVATE-TOKEN": token} if token else {}
    import httpx
    encoded = project_path.replace("/", "%2F")
    api = f"https://gitlab.com/api/v4/projects/{encoded}/merge_requests/{iid}"
    r = httpx.get(api, headers=headers, timeout=30)
    if r.status_code != 200:
        raise BotRepoError(f"GitLab MR fetch failed ({r.status_code}): {r.text[:300]}")
    data = r.json()
    return {
        "source_branch": data.get("source_branch") or "",
        "target_branch": data.get("target_branch") or "",
        "title": data.get("title") or "",
        "description": data.get("description") or "",
    }


def ensure_repo() -> Path:
    cache = BOT_REPO_CACHE_DIR
    cache.parent.mkdir(parents=True, exist_ok=True)
    if not (cache / ".git").exists():
        _log.info("cloning bot repo %s → %s", BOT_REPO_URL, cache)
        _run(["git", "clone", BOT_REPO_URL, str(cache)], cwd=cache.parent)
    else:
        _log.debug("bot repo cache exists at %s", cache)
    _log.debug("fetching latest refs")
    _run(["git", "fetch", "--all", "--prune"], cwd=cache)
    return cache


def checkout_for_change(pr_link: str | None) -> dict[str, Any]:
    repo = ensure_repo()
    meta: dict[str, Any] = {"repo_path": str(repo)}

    if pr_link:
        parsed = _parse_gitlab_mr(pr_link)
        if parsed:
            project_path, iid = parsed
            local = f"mr-{iid}"
            _log.info("checking out GitLab MR !%d (%s)", iid, project_path)
            try:
                meta.update(_fetch_gitlab_mr_branches(project_path, iid))
            except BotRepoError as e:
                _log.warning("GitLab MR metadata failed: %s", e)
                meta["mr_metadata_error"] = str(e)
            _run(["git", "fetch", "origin", f"refs/merge-requests/{iid}/head:{local}"], cwd=repo)
            _run(["git", "checkout", local], cwd=repo)
            meta["checked_out"] = local
            meta["mode"] = "gitlab_merge_request"
            _log.info("checked out branch %s (source=%s)", local, meta.get("source_branch"))
            return meta
        gh = re.search(r"github\.com/([^/]+)/([^/]+)/pull/(\d+)", pr_link)
        if gh:
            local = f"pr-{gh.group(3)}"
            _log.info("checking out GitHub PR #%s", gh.group(3))
            _run(["git", "fetch", "origin", f"pull/{gh.group(3)}/head:{local}"], cwd=repo)
            _run(["git", "checkout", local], cwd=repo)
            meta["checked_out"] = local
            meta["mode"] = "github_pr"
            return meta

    branch = BOT_REPO_DEFAULT_BRANCH
    _log.info("checking out default branch %s", branch)
    _run(["git", "checkout", branch], cwd=repo)
    try:
        _run(["git", "pull", "--ff-only", "origin", branch], cwd=repo)
    except BotRepoError:
        pass
    meta["checked_out"] = branch
    meta["mode"] = "development_default"
    return meta


def _safe_path(repo: Path, rel_path: str) -> Path:
    rel = rel_path.lstrip("/")
    target = (repo / rel).resolve()
    if not str(target).startswith(str(repo.resolve())):
        raise BotRepoError(f"Path escapes repo: {rel_path}")
    return target


def read_repo_file(path: str, *, pr_link: str | None = None, max_chars: int = 12000) -> dict[str, Any]:
    checkout_for_change(pr_link)
    repo = ensure_repo()
    target = _safe_path(repo, path)
    if not target.exists():
        return {"path": path, "error": "not_found"}
    text = target.read_text(errors="replace")
    return {"path": path, "content": text[:max_chars], "truncated": len(text) > max_chars}


def grep_repo(pattern: str, paths: list[str] | None = None, *, pr_link: str | None = None, max_matches: int = 40) -> dict[str, Any]:
    checkout_for_change(pr_link)
    repo = ensure_repo()
    search_paths = paths or ["."]
    cmd = ["git", "grep", "-n", "-I", "-E", pattern, "--"] + search_paths
    try:
        out = _run(cmd, cwd=repo)
    except BotRepoError:
        return {"pattern": pattern, "matches": []}
    matches = []
    for line in out.splitlines()[:max_matches]:
        if ":" not in line:
            continue
        file_part, rest = line.split(":", 1)
        if ":" in rest:
            ln, text = rest.split(":", 1)
            matches.append({"file": file_part, "line": ln, "text": text.strip()})
        else:
            matches.append({"file": file_part, "text": rest.strip()})
    return {"pattern": pattern, "matches": matches}
