"""Fetch VA blueprint from production Bot API (analysis_tool standalone)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

PRODUCTION_BOT_API_BASE_URL = "https://bot.thelevel.ai"
VA_BLUEPRINT_FILENAME = "va_blueprint.json"
EXTRACT_BLUEPRINT_PATH = "/service/va-blueprint/extract_blueprint"
REQUEST_TIMEOUT_S = 120


def resolve_production_bot_api_base_url(env: dict[str, str]) -> str:
    """Always use production Bot API for blueprint extract (never localhost)."""
    raw = (env.get("BOT_API_BASE_URL") or PRODUCTION_BOT_API_BASE_URL).strip().rstrip("/")
    lowered = raw.lower()
    if "localhost" in lowered or "127.0.0.1" in lowered:
        logger.warning(
            "Ignoring non-production BOT_API_BASE_URL=%r; using %s for VA blueprint",
            raw,
            PRODUCTION_BOT_API_BASE_URL,
        )
        return PRODUCTION_BOT_API_BASE_URL
    return raw


def fetch_va_blueprint(
    *,
    tenant_name: str,
    assistant_origin_id: str,
    bot_api_base_url: str,
    service_token: str | None = None,
    channel: str = "voice",
    runtime_mode: str = "DEBUG",
) -> dict[str, Any]:
    url = f"{bot_api_base_url.rstrip('/')}{EXTRACT_BLUEPRINT_PATH}"
    body = json.dumps(
        {
            "tenant": tenant_name,
            "origin_id": assistant_origin_id,
            "channel": channel,
            "runtime_mode": runtime_mode,
        }
    ).encode()
    headers = {
        "Content-Type": "application/json",
        "X-DTS-SCHEMA": tenant_name,
        "User-Agent": "analysis_tool/1.0",
        "Accept": "application/json",
    }
    if service_token:
        headers["Authorization"] = f"Bearer {service_token}"

    logger.debug(
        "VA blueprint POST %s tenant=%s assistant_origin_id=%s channel=%s runtime_mode=%s auth=%s",
        url,
        tenant_name,
        assistant_origin_id,
        channel,
        runtime_mode,
        "yes" if service_token else "no",
    )

    req = Request(url, data=body, headers=headers, method="POST")
    try:
        with urlopen(req, timeout=REQUEST_TIMEOUT_S) as resp:
            payload = json.loads(resp.read())
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"VA blueprint HTTP {exc.code}: {detail}") from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"VA blueprint fetch failed: {exc}") from exc

    if isinstance(payload, dict) and "data" in payload:
        blueprint = payload["data"]
    else:
        blueprint = payload
    if not isinstance(blueprint, dict):
        raise RuntimeError(f"VA blueprint response is not an object: {type(blueprint).__name__}")
    return blueprint


def write_va_blueprint_to_study(
    study_dir: Path | str,
    *,
    tenant_name: str,
    assistant_origin_id: str,
    env: dict[str, str],
    channel: str = "voice",
) -> Path:
    study_path = Path(study_dir)
    bot_api_base_url = resolve_production_bot_api_base_url(env)
    token = (env.get("PRODUCTION_SERVICE_TOKEN") or "").strip() or None

    blueprint = fetch_va_blueprint(
        tenant_name=tenant_name,
        assistant_origin_id=assistant_origin_id,
        bot_api_base_url=bot_api_base_url,
        service_token=token,
        channel=channel,
    )
    assistant_info = blueprint.get("assistant_info")
    if not isinstance(assistant_info, dict):
        logger.warning("VA blueprint response missing assistant_info; saving empty object")
        assistant_info = {}

    out_path = study_path / VA_BLUEPRINT_FILENAME
    out_path.write_text(json.dumps(assistant_info, indent=2, ensure_ascii=False) + "\n")
    logger.debug(
        "VA blueprint trimmed to assistant_info only and overwrote %s (top-level keys dropped)",
        out_path,
    )

    skill_count = len(assistant_info.get("skill_list") or [])
    logger.info(
        "VA blueprint saved to %s (%s skills, bot_api=%s)",
        out_path,
        skill_count,
        bot_api_base_url,
    )
    logger.debug(
        "VA blueprint metadata: tenant=%s assistant_origin_id=%s orchestration=%s",
        tenant_name,
        assistant_origin_id,
        assistant_info.get("orchestration_type"),
    )
    return out_path
