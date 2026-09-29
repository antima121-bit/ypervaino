#!/usr/bin/env python3
"""Smoke-test each model in llm_specs.yaml via OpenAI Responses API."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import yaml
from openai import OpenAI

from study_config import load_openai_api_key

TOOL_DIR = Path(__file__).resolve().parent
SPECS_PATH = TOOL_DIR / "llm_specs.yaml"


def load_specs() -> tuple[dict, dict[str, dict]]:
    raw = yaml.safe_load(SPECS_PATH.read_text(encoding="utf-8"))
    defaults = raw.get("defaults") or {}
    models = raw.get("models") or {}
    return defaults, models


def merge_spec(defaults: dict, entry: dict) -> dict:
    out = {
        "max_output_tokens": defaults.get("max_output_tokens", 128000),
        "text": dict(defaults.get("text") or {}),
        "api_model": entry["api_model"],
        "reasoning": dict(entry.get("reasoning") or {}),
    }
    return out


def smoke_one(client: OpenAI, key: str, spec: dict) -> tuple[bool, str]:
    try:
        resp = client.responses.create(
            model=spec["api_model"],
            input=[{"role": "user", "content": 'Reply with JSON only: {"ok": true}'}],
            text={
                **spec["text"],
                "format": {"type": "json_object"},
            },
            reasoning=spec["reasoning"],
            max_output_tokens=512,
        )
        if resp.status == "incomplete":
            reason = getattr(getattr(resp, "incomplete_details", None), "reason", None) or "incomplete"
            return False, str(reason)
        text = (resp.output_text or "").strip()
        if text:
            json.loads(text)
        return True, "ok"
    except Exception as exc:
        return False, str(exc).replace("\n", " ")[:500]


def main() -> int:
    defaults, models = load_specs()
    client = OpenAI(api_key=load_openai_api_key())
    results: list[tuple[str, str, bool, str]] = []

    for key in sorted(models.keys()):
        spec = merge_spec(defaults, models[key])
        ok, msg = smoke_one(client, key, spec)
        results.append((key, spec["api_model"], ok, msg))
        status = "OK" if ok else "FAIL"
        print(f"{status}\t{key}\t{spec['api_model']}\t{msg}")
        time.sleep(0.3)

    failed = [r for r in results if not r[2]]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
