"""Config and environment for analysis_tool (standalone; no ypervaino imports or repo-root .env)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time as dt_time, timezone
from pathlib import Path
from typing import Any

import yaml

TOOL_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = TOOL_DIR / "config.yaml"
DEFAULT_MODEL_NAME = "sol_high"
DEFAULT_CONCURRENCY = 10


@dataclass(frozen=True)
class AnalysisConfig:
    study_name: str
    tenant_name: str
    assistant_origin_id: str
    date_range_start: datetime
    date_range_end: datetime
    hypothesis: str | None = None
    model_name: str = DEFAULT_MODEL_NAME
    concurrency: int = DEFAULT_CONCURRENCY


def _parse_date_dd_mm_yyyy(value: str, *, end_of_day: bool) -> datetime:
    day = datetime.strptime(value.strip(), "%d-%m-%Y").date()
    if end_of_day:
        return datetime.combine(day, dt_time(23, 59, 59, 999999), tzinfo=timezone.utc)
    return datetime.combine(day, dt_time.min, tzinfo=timezone.utc)


def load_config(path: Path | str = DEFAULT_CONFIG_PATH) -> AnalysisConfig:
    config_path = Path(path)
    raw = yaml.safe_load(config_path.read_text()) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"Config root must be a mapping: {config_path}")

    required = (
        "study_name",
        "tenant_name",
        "assistant_origin_id",
        "date_range_start",
        "date_range_end",
    )
    missing = [k for k in required if not raw.get(k)]
    if missing:
        raise ValueError(f"Missing required config field(s): {', '.join(missing)}")

    hypothesis = raw.get("hypothesis")
    if hypothesis is not None and not isinstance(hypothesis, str):
        raise ValueError("hypothesis must be a string when set")
    hypothesis = hypothesis.strip() if isinstance(hypothesis, str) and hypothesis.strip() else None

    model_name = raw.get("model_name", DEFAULT_MODEL_NAME)
    if model_name is not None and not isinstance(model_name, str):
        raise ValueError("model_name must be a string when set")
    model_name = str(model_name).strip() if model_name else DEFAULT_MODEL_NAME

    concurrency_raw = raw.get("concurrency", DEFAULT_CONCURRENCY)
    try:
        concurrency = int(concurrency_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("concurrency must be an integer") from exc
    if concurrency < 1:
        raise ValueError("concurrency must be at least 1")

    return AnalysisConfig(
        study_name=str(raw["study_name"]).strip(),
        tenant_name=str(raw["tenant_name"]).strip(),
        assistant_origin_id=str(raw["assistant_origin_id"]).strip(),
        date_range_start=_parse_date_dd_mm_yyyy(str(raw["date_range_start"]), end_of_day=False),
        date_range_end=_parse_date_dd_mm_yyyy(str(raw["date_range_end"]), end_of_day=True),
        hypothesis=hypothesis,
        model_name=model_name,
        concurrency=concurrency,
    )


def config_to_yaml_dict(cfg: AnalysisConfig) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "study_name": cfg.study_name,
        "tenant_name": cfg.tenant_name,
        "assistant_origin_id": cfg.assistant_origin_id,
        "date_range_start": cfg.date_range_start.strftime("%d-%m-%Y"),
        "date_range_end": cfg.date_range_end.strftime("%d-%m-%Y"),
        "model_name": cfg.model_name,
        "concurrency": cfg.concurrency,
    }
    if cfg.hypothesis:
        payload["hypothesis"] = cfg.hypothesis
    return payload


def config_to_yaml(cfg: AnalysisConfig) -> str:
    return yaml.safe_dump(config_to_yaml_dict(cfg), sort_keys=False, allow_unicode=True)


def write_config(path: Path | str, cfg: AnalysisConfig) -> None:
    """Serialize AnalysisConfig to YAML (dates as DD-MM-YYYY strings)."""
    config_path = Path(path)
    config_path.write_text(config_to_yaml(cfg), encoding="utf-8")


def config_from_form(
    *,
    study_name: str,
    tenant_name: str,
    assistant_origin_id: str,
    date_range_start: str,
    date_range_end: str,
    hypothesis: str,
    model_name: str,
    concurrency: int,
) -> AnalysisConfig:
    return AnalysisConfig(
        study_name=study_name.strip(),
        tenant_name=tenant_name.strip(),
        assistant_origin_id=assistant_origin_id.strip(),
        date_range_start=_parse_date_dd_mm_yyyy(date_range_start, end_of_day=False),
        date_range_end=_parse_date_dd_mm_yyyy(date_range_end, end_of_day=True),
        hypothesis=hypothesis.strip(),
        model_name=model_name.strip(),
        concurrency=concurrency,
    )


def _parse_env_file(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, val = line.split("=", 1)
            env[key.strip()] = val.strip()
    return env


def load_env(*, require_mongo: bool = True) -> dict[str, str]:
    """Load analysis_tool/.env and optional .env.mongo only."""
    candidates = [TOOL_DIR / ".env", TOOL_DIR / ".env.mongo"]
    merged: dict[str, str] = {}
    for candidate in candidates:
        if candidate.is_file():
            merged.update(_parse_env_file(candidate))
    if require_mongo and ("MONGO_URI" not in merged or "MONGO_DB_NAME" not in merged):
        raise FileNotFoundError(
            "Mongo credentials not found. Set MONGO_URI and MONGO_DB_NAME in analysis_tool/.env "
            f"(tried: {', '.join(str(p) for p in candidates)})"
        )
    return merged


def load_openai_api_key() -> str:
    merged = load_env(require_mongo=False)
    key = merged.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("OPENAI_API_KEY not found. Set it in analysis_tool/.env")
    return key
