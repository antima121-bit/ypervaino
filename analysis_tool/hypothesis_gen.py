"""Generate evaluable hypotheses from user-provided study text via structured LLM output."""

from __future__ import annotations

import argparse
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openai import OpenAI

from llm_specs_loader import resolve_model_responses_kwargs
from study_config import DEFAULT_MODEL_NAME, load_config, load_openai_api_key

logger = logging.getLogger(__name__)

TOOL_DIR = Path(__file__).resolve().parent
DEFAULT_EVENT_SCHEMA_PATH = TOOL_DIR / "event_schema_descriptions.json"
DEFAULT_OPS_SCHEMA_PATH = TOOL_DIR / "hypothesis_ordered_predicate_schema.json"
DEFAULT_LLM_SCHEMA_PATH = TOOL_DIR / "hypothesis_gen_schema.json"
DEFAULT_OUTPUT_FILENAME = "generated_hypotheses.json"


@dataclass(frozen=True)
class HypothesisGenInputs:
    event_schema_path: Path
    ops_schema_path: Path
    deep_union_path: Path
    blueprint_path: Path
    user_hypotheses: list[dict[str, str]]


def load_llm_response_format(schema_path: Path) -> dict[str, Any]:
    raw = json.loads(schema_path.read_text(encoding="utf-8"))
    meta = raw.pop("_meta", {}) or {}
    name = str(meta.get("name") or schema_path.stem)
    strict = bool(meta.get("strict", False))
    return {
        "type": "json_schema",
        "name": name,
        "strict": strict,
        "schema": raw,
    }


def _read_json_text(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"Missing input file: {path}")
    return path.read_text(encoding="utf-8")


def user_hypotheses_from_config_text(hypothesis: str | None) -> list[dict[str, str]]:
    if not hypothesis or not hypothesis.strip():
        raise ValueError("Config hypothesis is empty; user-provided hypothesis is required")
    text = hypothesis.strip()
    title = text.splitlines()[0].strip()[:120] or "user_hypothesis"
    return [{"title": title, "body": text}]


def build_hypothesis_generation_prompt(
    inputs: HypothesisGenInputs,
    *,
    output_schema: dict[str, Any],
) -> str:
    event_schema_text = _read_json_text(inputs.event_schema_path)
    ops_schema_text = _read_json_text(inputs.ops_schema_path)
    deep_union_text = _read_json_text(inputs.deep_union_path)
    blueprint_text = _read_json_text(inputs.blueprint_path)

    user_blocks = []
    for idx, item in enumerate(inputs.user_hypotheses, start=1):
        user_blocks.append(
            f"### User hypothesis {idx}\nTitle: {item['title']}\n\n{item['body']}\n"
        )
    user_section = "\n".join(user_blocks)

    schema_for_prompt = json.dumps(output_schema.get("schema", output_schema), indent=2)

    return f"""<context>
You are authoring machine-evaluable hypotheses for a voice/chat bot quality study.
Each hypothesis is evaluated per session on parsed_trace.ordered_events only (not raw logs, not accumulated_events).
Predicates must compile to the four approved operations implemented in analysis_tool/ops.py.
</context>

<input_semantics>
1. event_schema_descriptions.json — Semantic and structural documentation for the nine event types that appear in parsed_trace.ordered_events (payload shapes, tool-name keys, content fields for regex, predicate path conventions).

2. hypothesis_ordered_predicate_schema.json — Formal specification of the four ordered predicate operations (event_exists, meta_value_operation, regex, is_ordered_seq_present), including composition with and/or/not, sequence cursor semantics, and worked examples (e.g. payment hallucination).

3. deep_union_over_parsed_traces.json — Cohort union of values observed in ordered_events across parsed sessions: valid tool names, nested field paths, and primitive value samples (capped). Use this to ground tool names and field paths; do not invent tools or paths not supported by union + blueprint.

4. va_blueprint.json — assistant_info for the tenant assistant (skills, tools, orchestration). Use for canonical tool names and bot behavior context when translating the user's natural-language hypothesis into predicates.
</input_semantics>

<task>
Generate structured hypotheses JSON that conforms exactly to the output JSON Schema below.

For each user-provided hypothesis only (same count as user inputs — do not add extra hypotheses):
- hypothesis_id: snake_case slug from title
- title: short label aligned with the user text
- user_provided_text: preserve the user's hypothesis wording
- summary: plain-language scope + claim
- polarity: "negative" if a higher match rate indicates a defect (e.g. hallucination, missing required tool); "positive" if a higher rate is desired behavior
- scope_predicate: boolean AST — which sessions are in the denominator (when scope is false, session is skipped / not applicable)
- claim_predicate: boolean AST — pattern tested on applicable sessions (match = hypothesis matched for that session)
- tool_names_referenced: list every tool name string used in meta_value_operation / is_ordered_seq_present paths

Output JSON Schema (also enforced by the API response format):
{schema_for_prompt}
</task>

<instructions>
- Use ONLY these leaf operations: event_exists, meta_value_operation, regex, is_ordered_seq_present.
- Compose with op "and", "or", "not" and operands/operand arrays as defined in the schema.
- For meta_value_operation use field compare_op (not op) for ==, !=, exists, in, comparisons.
- Paths for meta_value_operation start with event_type then nested dict keys; TOOL_CALL_RESULT and DEBUG.TOOL_INVOKED require the tool name as the first key after the event type.
- regex applies only to USER_QUERY.content (user_turn) or RESPONSE.FINAL.content (bot_turn).
- Do not reference accumulated_events, Transcript-only paths, or raw log event_value layouts from legacy docs.
- Do not invent new event types, ops, or tools not found in deep_union or va_blueprint when a specific tool is required.
- Translate the user hypothesis faithfully; do not broaden scope beyond what the user asked.
- Prefer explicit tool lists (or) when multiple payment tools exist in union/blueprint.
</instructions>

<user_provided_hypothesis>
{user_section}
</user_provided_hypothesis>

<inputs>

## event_schema_descriptions.json

```json
{event_schema_text}
```

## hypothesis_ordered_predicate_schema.json

```json
{ops_schema_text}
```

## deep_union_over_parsed_traces.json

```json
{deep_union_text}
```

## va_blueprint.json

```json
{blueprint_text}
```

</inputs>
"""


def _strip_json_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def call_hypothesis_llm(
    prompt: str,
    *,
    api_key: str,
    response_format: dict[str, Any],
    model_responses_kwargs: dict[str, Any],
) -> dict[str, Any]:
    client = OpenAI(api_key=api_key)
    text_cfg = dict(model_responses_kwargs.get("text") or {})
    text_cfg["format"] = response_format
    kwargs: dict[str, Any] = {
        "model": model_responses_kwargs["model"],
        "input": [{"role": "user", "content": prompt}],
        "text": text_cfg,
        "reasoning": model_responses_kwargs.get("reasoning") or {"effort": "none"},
        "max_output_tokens": model_responses_kwargs.get("max_output_tokens", 128000),
    }
    resp = client.responses.create(**kwargs)
    if resp.status == "incomplete":
        reason = getattr(getattr(resp, "incomplete_details", None), "reason", None) or "unknown"
        raise RuntimeError(f"LLM response incomplete: {reason}")
    raw = resp.output_text or "{}"
    return json.loads(_strip_json_fences(raw))


def generate_hypotheses(
    inputs: HypothesisGenInputs,
    *,
    llm_schema_path: Path = DEFAULT_LLM_SCHEMA_PATH,
    model_name: str = DEFAULT_MODEL_NAME,
    api_key: str | None = None,
) -> dict[str, Any]:
    if not inputs.user_hypotheses:
        raise ValueError("At least one user-provided hypothesis is required")

    response_format = load_llm_response_format(llm_schema_path)
    prompt = build_hypothesis_generation_prompt(inputs, output_schema=response_format)
    key = api_key or load_openai_api_key()
    model_kwargs = resolve_model_responses_kwargs(model_name)

    logger.info(
        "Calling LLM model_name=%s api_model=%s effort=%s for %s user hypothesis(es)",
        model_name,
        model_kwargs["model"],
        (model_kwargs.get("reasoning") or {}).get("effort"),
        len(inputs.user_hypotheses),
    )
    result = call_hypothesis_llm(
        prompt,
        api_key=key,
        response_format=response_format,
        model_responses_kwargs=model_kwargs,
    )

    if not isinstance(result.get("hypotheses"), list) or not result["hypotheses"]:
        raise RuntimeError("LLM returned no hypotheses array")

    if len(result["hypotheses"]) != len(inputs.user_hypotheses):
        logger.warning(
            "Expected %s hypotheses, got %s",
            len(inputs.user_hypotheses),
            len(result["hypotheses"]),
        )
    return result


def write_generated_hypotheses(study_dir: Path | str, payload: dict[str, Any]) -> Path:
    out = Path(study_dir) / DEFAULT_OUTPUT_FILENAME
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    logger.info("Wrote generated hypotheses to %s", out)
    return out


def default_inputs_for_study(
    study_dir: Path | str,
    user_hypotheses: list[dict[str, str]],
    *,
    event_schema_path: Path | None = None,
    ops_schema_path: Path | None = None,
) -> HypothesisGenInputs:
    study = Path(study_dir)
    return HypothesisGenInputs(
        event_schema_path=event_schema_path or DEFAULT_EVENT_SCHEMA_PATH,
        ops_schema_path=ops_schema_path or DEFAULT_OPS_SCHEMA_PATH,
        deep_union_path=study / "deep_union_over_parsed_traces.json",
        blueprint_path=study / "va_blueprint.json",
        user_hypotheses=user_hypotheses,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate structured hypotheses for a study folder.")
    parser.add_argument("--study-dir", type=Path, required=True, help="Study output directory")
    parser.add_argument("--config", type=Path, default=TOOL_DIR / "config.yaml")
    parser.add_argument("--event-schema", type=Path, default=DEFAULT_EVENT_SCHEMA_PATH)
    parser.add_argument("--ops-schema", type=Path, default=DEFAULT_OPS_SCHEMA_PATH)
    parser.add_argument("--llm-schema", type=Path, default=DEFAULT_LLM_SCHEMA_PATH)
    parser.add_argument(
        "--model-name",
        type=str,
        default=None,
        help="Override config model_name (llm_specs.yaml key)",
    )
    args = parser.parse_args(argv)

    from log_setup import configure_logging

    configure_logging(logging.INFO)

    cfg = load_config(args.config)
    user_hyps = user_hypotheses_from_config_text(cfg.hypothesis)
    gen_inputs = default_inputs_for_study(
        args.study_dir,
        user_hyps,
        event_schema_path=args.event_schema,
        ops_schema_path=args.ops_schema,
    )
    model_name = args.model_name or cfg.model_name
    payload = generate_hypotheses(
        gen_inputs,
        llm_schema_path=args.llm_schema,
        model_name=model_name,
    )
    write_generated_hypotheses(args.study_dir, payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
