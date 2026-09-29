"""Tests for hypothesis_eval (no LLM)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from hypothesis_eval import evaluate_hypothesis_on_session, run_hypothesis_evaluation


class TestHypothesisEval(unittest.TestCase):
    def test_polarity_negative_pass_when_claim_false(self) -> None:
        trace = {
            "ordered_events": [
                {"USER_QUERY": {"content": "pay bill", "event_value": {}}},
                {"RESPONSE.FINAL": {"content": "ok", "event_value": {}}},
            ]
        }
        hyp = {
            "hypothesis_id": "t1",
            "polarity": "negative",
            "scope_predicate": {"op": "regex", "turn_type": "user_turn", "pattern": "pay"},
            "claim_predicate": {
                "op": "regex",
                "turn_type": "bot_turn",
                "pattern": "payment successful",
            },
        }
        r = evaluate_hypothesis_on_session(trace, hyp)
        self.assertTrue(r["applicable"])
        self.assertFalse(r["claim_matched"])
        self.assertTrue(r["passed"])

    def test_end_to_end_eval_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            parsed = root / "parsed_traces"
            parsed.mkdir()
            trace = {
                "ordered_events": [{"USER_QUERY": {"content": "hello", "event_value": {}}}],
                "accumulated_events": {"TOKEN_USAGE_DETAILS": {"input_tokens": [5]}},
            }
            (parsed / "s1.json").write_text(json.dumps(trace))
            (root / "generated_hypotheses.json").write_text(
                json.dumps(
                    {
                        "hypotheses": [
                            {
                                "hypothesis_id": "h1",
                                "title": "t",
                                "polarity": "positive",
                                "scope_predicate": {"op": "event_exists", "event_name": "USER_QUERY"},
                                "claim_predicate": {"op": "event_exists", "event_name": "USER_QUERY"},
                            }
                        ]
                    }
                )
            )
            paths = run_hypothesis_evaluation(root)
            per_h = json.loads(paths["per_hypothesis"].read_text())
            self.assertEqual(per_h["hypotheses"]["h1"]["n_applicable"], 1)
            self.assertEqual(per_h["hypotheses"]["h1"]["n_matched"], 1)
            self.assertIn("s1", per_h["hypotheses"]["h1"]["passed_session_ids"])
            self.assertIn("accumulated_cohort_metrics", per_h)


if __name__ == "__main__":
    unittest.main()
