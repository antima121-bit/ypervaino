from __future__ import annotations

import json
import re
from typing import Any

from openai import OpenAI

from ypervaino.llm_schemas import load_llm_schema
from ypervaino.settings import ANTHROPIC_API_KEY, OPENAI_API_KEY

DEFAULT_MODEL = "gpt-5.6"
DEFAULT_REASONING: dict[str, Any] = {"effort": "high", "mode": "pro"}
DEFAULT_TEXT: dict[str, Any] = {"verbosity": "medium"}
DEFAULT_MAX_OUTPUT_TOKENS = 128_000

DEFAULT_LLM_CONFIG: dict[str, Any] = {
    "model": DEFAULT_MODEL,
    "reasoning": DEFAULT_REASONING,
    "text": DEFAULT_TEXT,
    "max_output_tokens": DEFAULT_MAX_OUTPUT_TOKENS,
}


def _strip_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _resolve_json_format(
    *,
    schema: dict[str, Any] | None,
    schema_name: str | None,
    text: dict[str, Any] | None,
) -> dict[str, Any]:
    text_cfg = {**DEFAULT_TEXT, **(text or {})}
    if schema is not None:
        text_cfg["format"] = schema
    elif schema_name is not None:
        text_cfg["format"] = load_llm_schema(schema_name)
    else:
        text_cfg.setdefault("format", {"type": "json_object"})
    return text_cfg


class LLMClient:
    def json_completion(
        self,
        prompt: str,
        model: str = DEFAULT_MODEL,
        max_tokens: int = 4000,
        *,
        schema: dict[str, Any] | None = None,
        schema_name: str | None = None,
        reasoning: dict[str, Any] | None = None,
        text: dict[str, Any] | None = None,
        max_output_tokens: int | None = None,
    ) -> dict[str, Any]:
        reasoning_cfg = DEFAULT_REASONING if reasoning is None else reasoning
        max_out = DEFAULT_MAX_OUTPUT_TOKENS if max_output_tokens is None else max_output_tokens

        if OPENAI_API_KEY:
            client = OpenAI(api_key=OPENAI_API_KEY)
            text_cfg = _resolve_json_format(schema=schema, schema_name=schema_name, text=text)
            kwargs: dict[str, Any] = {
                "model": model,
                "input": [{"role": "user", "content": prompt}],
                "text": text_cfg,
                "reasoning": reasoning_cfg,
                "max_output_tokens": max_out,
            }
            resp = client.responses.create(**kwargs)
            if resp.status == "incomplete":
                reason = getattr(getattr(resp, "incomplete_details", None), "reason", None) or "unknown"
                raise RuntimeError(f"LLM response incomplete: {reason}")
            raw = resp.output_text or "{}"
            return json.loads(_strip_fences(raw))

        if ANTHROPIC_API_KEY:
            import urllib.request
            body = json.dumps({
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt + "\n\nReply with JSON only."}],
            }).encode()
            req = urllib.request.Request(
                "https://api.anthropic.com/v1/messages",
                data=body,
                headers={
                    "content-type": "application/json",
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read())
            text_out = data["content"][0]["text"]
            return json.loads(_strip_fences(text_out))

        raise RuntimeError("No LLM API key configured (OPENAI_API_KEY or ANTHROPIC_API_KEY)")
