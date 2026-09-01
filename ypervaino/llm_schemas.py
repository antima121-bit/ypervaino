from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_SCHEMA_DIR = Path(__file__).resolve().parent.parent / "config" / "llm_schemas"


@lru_cache(maxsize=32)
def load_llm_schema(name: str, *, strict: bool | None = None) -> dict[str, Any]:
    """Load a JSON Schema for structured LLM output (OpenAI json_schema format)."""
    path = _SCHEMA_DIR / f"{name}.json"
    if not path.exists():
        raise KeyError(f"Unknown LLM schema: {name} ({path})")
    raw = json.loads(path.read_text(encoding="utf-8"))
    meta = raw.pop("_meta", {}) or {}
    use_strict = strict if strict is not None else bool(meta.get("strict", True))
    return {
        "type": "json_schema",
        "name": str(meta.get("name") or name),
        "strict": use_strict,
        "schema": raw,
    }
