"""Tests for hypothesis_gen prompt and schema loading (no LLM calls)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from hypothesis_gen import (
    DEFAULT_LLM_SCHEMA_PATH,
    HypothesisGenInputs,
    build_hypothesis_generation_prompt,
    load_llm_response_format,
    user_hypotheses_from_config_text,
)


class TestHypothesisGen(unittest.TestCase):
    def test_user_hypothesis_required(self) -> None:
        with self.assertRaises(ValueError):
            user_hypotheses_from_config_text("  ")

    def test_prompt_contains_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            event = root / "event.json"
            ops = root / "ops.json"
            union = root / "union.json"
            bp = root / "bp.json"
            for p, doc in [
                (event, {"ordered_event_types": {}}),
                (ops, {"operations": {}}),
                (union, {"union": {}}),
                (bp, {"skill_list": []}),
            ]:
                p.write_text(json.dumps(doc))

            fmt = load_llm_response_format(DEFAULT_LLM_SCHEMA_PATH)
            prompt = build_hypothesis_generation_prompt(
                HypothesisGenInputs(
                    event_schema_path=event,
                    ops_schema_path=ops,
                    deep_union_path=union,
                    blueprint_path=bp,
                    user_hypotheses=[{"title": "Payment hallucination", "body": "Check payment success without tool"}],
                ),
                output_schema=fmt,
            )
            self.assertIn("<context>", prompt)
            self.assertIn("<input_semantics>", prompt)
            self.assertIn("<task>", prompt)
            self.assertIn("<instructions>", prompt)
            self.assertIn("<user_provided_hypothesis>", prompt)
            self.assertIn("<inputs>", prompt)
            self.assertIn("Payment hallucination", prompt)
            self.assertIn("event_exists", prompt)


if __name__ == "__main__":
    unittest.main()
