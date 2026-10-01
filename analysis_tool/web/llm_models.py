"""Map UI api_model + effort to llm_specs.yaml model_name keys."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from llm_specs_loader import load_llm_specs

TOOL_DIR = Path(__file__).resolve().parent.parent
DEFAULT_LLM_SPECS_PATH = TOOL_DIR / "llm_specs.yaml"

DEFAULT_API_MODEL = "gpt-5.6-sol"
DEFAULT_EFFORT = "high"
EFFORT_CHOICES = ("none", "low", "high")


def list_unique_api_models(specs_path: Path | str = DEFAULT_LLM_SPECS_PATH) -> list[str]:
    raw = load_llm_specs(specs_path)
    models = raw.get("models") or {}
    seen: list[str] = []
    for entry in models.values():
        if not isinstance(entry, dict):
            continue
        api_model = entry.get("api_model")
        if isinstance(api_model, str) and api_model not in seen:
            seen.append(api_model)
    return seen


def resolve_model_name(
    api_model: str,
    effort: str,
    *,
    specs_path: Path | str = DEFAULT_LLM_SPECS_PATH,
) -> str:
    if effort not in EFFORT_CHOICES:
        raise ValueError(f"effort must be one of {EFFORT_CHOICES}, got {effort!r}")
    raw = load_llm_specs(specs_path)
    models: dict[str, Any] = raw.get("models") or {}
    for key, entry in models.items():
        if not isinstance(entry, dict):
            continue
        reasoning = entry.get("reasoning") or {}
        if entry.get("api_model") == api_model and reasoning.get("effort") == effort:
            return key
    raise ValueError(f"No llm_specs entry for api_model={api_model!r} effort={effort!r}")


def llm_form_options(specs_path: Path | str = DEFAULT_LLM_SPECS_PATH) -> dict[str, Any]:
    return {
        "api_models": list_unique_api_models(specs_path),
        "efforts": list(EFFORT_CHOICES),
        "defaults": {"api_model": DEFAULT_API_MODEL, "effort": DEFAULT_EFFORT},
    }
