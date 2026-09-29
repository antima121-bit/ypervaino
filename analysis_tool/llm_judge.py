"""LLM judge for rule-engine failed (session, hypothesis) pairs."""

from __future__ import annotations

import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openai import OpenAI

from hypothesis_gen import DEFAULT_EVENT_SCHEMA_PATH, load_llm_response_format
from llm_specs_loader import resolve_model_responses_kwargs
from study_config import load_openai_api_key

logger = logging.getLogger(__name__)

TOOL_DIR = Path(__file__).resolve().parent
JUDGE_SCHEMA_PATH = TOOL_DIR / "llm_judge_schema.json"
JUDGE_OUTPUT_FILENAME = "llm_judge_results.json"
JUDGE_RETRY_COUNT = 3


@dataclass(frozen=True)
class JudgePair:
    session_id: str
    hypothesis_id: str


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _strip_json_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def load_failed_pairs(study_dir: Path) -> tuple[list[JudgePair], dict[str, dict[str, Any]]]:
    """Pairs where rule engine: applicable and passed is false."""
    eval_path = study_dir / "hypothesis_eval" / "per_session_id.json"
    hyp_path = study_dir / "generated_hypotheses.json"
    if not eval_path.is_file() or not hyp_path.is_file():
        raise FileNotFoundError("Need hypothesis_eval/per_session_id.json and generated_hypotheses.json")

    hyp_doc = json.loads(hyp_path.read_text(encoding="utf-8"))
    hyp_by_id: dict[str, dict[str, Any]] = {
        h["hypothesis_id"]: h for h in hyp_doc.get("hypotheses") or [] if h.get("hypothesis_id")
    }

    per_session = json.loads(eval_path.read_text(encoding="utf-8"))
    sessions = per_session.get("sessions") or {}

    pairs: list[JudgePair] = []
    for session_id, record in sessions.items():
        for hid, result in (record.get("hypotheses") or {}).items():
            if hid not in hyp_by_id:
                continue
            if result.get("applicable") and not result.get("passed"):
                pairs.append(JudgePair(session_id=session_id, hypothesis_id=hid))

    return pairs, hyp_by_id


def build_llm_judge_prompt(
    *,
    session_id: str,
    hypothesis: dict[str, Any],
    ordered_events: list[Any],
    event_schema_text: str,
    deep_union_text: str,
    blueprint_text: str,
    output_schema: dict[str, Any],
) -> str:
    schema_text = json.dumps(output_schema.get("schema", output_schema), indent=2)
    ordered_json = json.dumps(ordered_events, indent=2, ensure_ascii=False)
    polarity = hypothesis.get("polarity", "negative")

    return f"""<context>
You are an independent judge for a voice/chat bot quality study.

You will see one conversation session (as ordered_events) and one hypothesis written in plain language.
Your job is to decide whether this session should **pass** or **fail** that hypothesis.

**Polarity for this hypothesis:** `{polarity}`

- If polarity is **positive**: **pass** means the session shows the desired behavior described in the hypothesis. **fail** means it does not.
- If polarity is **negative** (common for defects like hallucinations): **pass** means the problem described in the hypothesis is **not** present in this session. **fail** means the problem **is** present.

Use only the evidence in ordered_events. Do not guess events or tool calls that are not in the timeline.
</context>

<input_semantics>
**ordered_events (this session)** — The full time-ordered list of events for session `{session_id}`. Each item has one event type key (for example USER_QUERY, RESPONSE.FINAL, TOOL_CALL_RESULT). This is the only direct evidence for your decision.

**event_schema_descriptions.json** — Explains what each ordered event type means and how fields are shaped (for example tool names as keys under TOOL_CALL_RESULT).

**hypothesis block below** — Title, the user's original wording, a short summary, and polarity. You do not receive any rule-engine predicates or code.

**deep_union_over_parsed_traces.json** — Values seen across many sessions in this study (tool names, nested fields). Built by merging ordered_events from all parsed sessions, with caps on how many unique values are kept. Use this to interpret tool names and fields that appear in this session.

**va_blueprint.json** — The assistant configuration (skills, tools, instructions). Helps you understand what tools exist and what the bot is supposed to do.
</input_semantics>

<task>
Return JSON matching this schema exactly:
{schema_text}

- **result**: either `"pass"` or `"fail"` using the polarity rules above.
- **description**: a clear, simple explanation in complete sentences. Mention specific event types, tool names, or message content from ordered_events that support your decision.
</task>

<instructions>
- Read the hypothesis carefully, then scan ordered_events from start to finish.
- For payment/tool hypotheses: a tool call must appear in ordered_events (TOOL_CALL_RESULT or DEBUG.TOOL_INVOKED with the tool name as a key) to count as called.
- For text claims: use USER_QUERY content for user turns and RESPONSE.FINAL content for bot turns.
- If the trace is ambiguous, say so in description and choose **fail** unless the evidence clearly supports **pass**.
- Do not mention rule engines, predicates, or automation — only the trace and hypothesis.
</instructions>

<hypothesis>
Title: {hypothesis.get("title", "")}

User-provided text:
{hypothesis.get("user_provided_text", "")}

Summary:
{hypothesis.get("summary", "")}

Polarity: {polarity}
</hypothesis>

<inputs>

## ordered_events (session {session_id})

```json
{ordered_json}
```

## event_schema_descriptions.json

```json
{event_schema_text}
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


def _call_judge_llm(
    prompt: str,
    *,
    api_key: str,
    response_format: dict[str, Any],
    model_responses_kwargs: dict[str, Any],
) -> dict[str, Any]:
    client = OpenAI(api_key=api_key)
    text_cfg = dict(model_responses_kwargs.get("text") or {})
    text_cfg["format"] = response_format
    resp = client.responses.create(
        model=model_responses_kwargs["model"],
        input=[{"role": "user", "content": prompt}],
        text=text_cfg,
        reasoning=model_responses_kwargs.get("reasoning") or {"effort": "none"},
        max_output_tokens=model_responses_kwargs.get("max_output_tokens", 128000),
    )
    if resp.status == "incomplete":
        reason = getattr(getattr(resp, "incomplete_details", None), "reason", None) or "unknown"
        raise RuntimeError(f"LLM response incomplete: {reason}")
    raw = resp.output_text or "{}"
    data = json.loads(_strip_json_fences(raw))
    if data.get("result") not in ("pass", "fail"):
        raise ValueError(f"Invalid judge result: {data.get('result')!r}")
    return data


def _judge_one_pair(
    pair: JudgePair,
    *,
    study_dir: Path,
    hyp_by_id: dict[str, dict[str, Any]],
    event_schema_text: str,
    deep_union_text: str,
    blueprint_text: str,
    response_format: dict[str, Any],
    model_responses_kwargs: dict[str, Any],
    api_key: str,
) -> tuple[JudgePair, dict[str, Any] | None, str | None]:
    parsed_path = study_dir / "parsed_traces" / f"{pair.session_id}.json"
    if not parsed_path.is_file():
        return pair, None, f"missing parsed trace: {parsed_path}"

    parsed = json.loads(parsed_path.read_text(encoding="utf-8"))
    ordered = parsed.get("ordered_events")
    if not isinstance(ordered, list):
        ordered = []

    hypothesis = hyp_by_id[pair.hypothesis_id]
    prompt = build_llm_judge_prompt(
        session_id=pair.session_id,
        hypothesis=hypothesis,
        ordered_events=ordered,
        event_schema_text=event_schema_text,
        deep_union_text=deep_union_text,
        blueprint_text=blueprint_text,
        output_schema=response_format,
    )

    last_err: str | None = None
    for attempt in range(1, JUDGE_RETRY_COUNT + 1):
        try:
            result = _call_judge_llm(
                prompt,
                api_key=api_key,
                response_format=response_format,
                model_responses_kwargs=model_responses_kwargs,
            )
            return pair, result, None
        except Exception as exc:
            last_err = str(exc)
            logger.warning(
                "LLM judge attempt %s/%s failed session=%s hypothesis=%s: %s",
                attempt,
                JUDGE_RETRY_COUNT,
                pair.session_id,
                pair.hypothesis_id,
                exc,
            )
            if attempt < JUDGE_RETRY_COUNT:
                time.sleep(attempt)
    return pair, None, last_err


def run_llm_judge(
    study_dir: Path | str,
    *,
    model_name: str,
    concurrency: int = 10,
) -> Path:
    study_path = Path(study_dir)
    pairs, hyp_by_id = load_failed_pairs(study_path)

    out_dir = study_path / "hypothesis_eval"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / JUDGE_OUTPUT_FILENAME

    hypotheses_out: dict[str, dict[str, dict[str, str]]] = {hid: {} for hid in hyp_by_id}

    if not pairs:
        payload = {
            "meta": {
                "study_dir": str(study_path),
                "model_name": model_name,
                "pairs_judged": 0,
                "note": "No applicable rule-engine failures to judge.",
            },
            "hypotheses": hypotheses_out,
        }
        out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        logger.info("LLM judge: no failed pairs; wrote %s", out_path)
        return out_path

    event_schema_text = _read_text(DEFAULT_EVENT_SCHEMA_PATH)
    deep_union_text = _read_text(study_path / "deep_union_over_parsed_traces.json")
    blueprint_text = _read_text(study_path / "va_blueprint.json")
    response_format = load_llm_response_format(JUDGE_SCHEMA_PATH)
    model_kwargs = resolve_model_responses_kwargs(model_name)
    api_key = load_openai_api_key()

    workers = min(max(concurrency, 1), len(pairs))
    errors: list[dict[str, str]] = []
    done = 0

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                _judge_one_pair,
                pair,
                study_dir=study_path,
                hyp_by_id=hyp_by_id,
                event_schema_text=event_schema_text,
                deep_union_text=deep_union_text,
                blueprint_text=blueprint_text,
                response_format=response_format,
                model_responses_kwargs=model_kwargs,
                api_key=api_key,
            ): pair
            for pair in pairs
        }
        for future in as_completed(futures):
            pair, result, err = future.result()
            done += 1
            if result:
                hypotheses_out[pair.hypothesis_id][pair.session_id] = {
                    "result": result["result"],
                    "description": result["description"],
                }
            else:
                errors.append(
                    {
                        "session_id": pair.session_id,
                        "hypothesis_id": pair.hypothesis_id,
                        "error": err or "unknown",
                    }
                )
            logger.info("LLM judge progress %s/%s", done, len(pairs))

    payload = {
        "meta": {
            "study_dir": str(study_path),
            "model_name": model_name,
            "api_model": model_kwargs["model"],
            "reasoning_effort": (model_kwargs.get("reasoning") or {}).get("effort"),
            "concurrency": workers,
            "pairs_requested": len(pairs),
            "pairs_judged_ok": len(pairs) - len(errors),
            "pairs_failed": len(errors),
            "errors": errors,
        },
        "hypotheses": hypotheses_out,
    }
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    logger.info("LLM judge results written to %s", out_path)
    return out_path
