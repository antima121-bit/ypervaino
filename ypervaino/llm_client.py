from __future__ import annotations

import json
import re
from typing import Any

from openai import OpenAI

from ypervaino.settings import ANTHROPIC_API_KEY, OPENAI_API_KEY


def _strip_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


class LLMClient:
    def json_completion(self, prompt: str, model: str = "gpt-4.1-mini", max_tokens: int = 4000) -> dict[str, Any]:
        if OPENAI_API_KEY:
            client = OpenAI(api_key=OPENAI_API_KEY)
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                max_tokens=max_tokens,
                temperature=0.2,
            )
            text = resp.choices[0].message.content or "{}"
            return json.loads(_strip_fences(text))

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
            text = data["content"][0]["text"]
            return json.loads(_strip_fences(text))

        raise RuntimeError("No LLM API key configured (OPENAI_API_KEY or ANTHROPIC_API_KEY)")
