"""Resolve config model_name to OpenAI Responses API parameters."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

TOOL_DIR = Path(__file__).resolve().parent
DEFAULT_LLM_SPECS_PATH = TOOL_DIR / "llm_specs.yaml"
DEFAULT_MODEL_NAME = "sol_high"


def load_llm_specs(path: Path | str = DEFAULT_LLM_SPECS_PATH) -> dict[str, Any]:
    spec_path = Path(path)
    raw = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"llm_specs root must be a mapping: {spec_path}")
    return raw


def resolve_model_responses_kwargs(
    model_name: str,
    *,
    specs_path: Path | str = DEFAULT_LLM_SPECS_PATH,
) -> dict[str, Any]:
    """Return kwargs for OpenAI client.responses.create (model, reasoning, max_output_tokens, text)."""
    raw = load_llm_specs(specs_path)
    models = raw.get("models")
    if not isinstance(models, dict):
        raise ValueError("llm_specs.yaml missing 'models' mapping")

    entry = models.get(model_name)
    if not isinstance(entry, dict):
        known = ", ".join(sorted(models.keys()))
        raise KeyError(f"Unknown model_name {model_name!r} in llm_specs.yaml (known: {known})")

    defaults = raw.get("defaults") or {}
    text = dict(defaults.get("text") or {})
    return {
        "model": entry["api_model"],
        "reasoning": dict(entry.get("reasoning") or {}),
        "max_output_tokens": int(defaults.get("max_output_tokens", 128000)),
        "text": text,
        "model_name": model_name,
    }
