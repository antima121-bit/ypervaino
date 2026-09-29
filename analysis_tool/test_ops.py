"""Tests for analysis_tool.ops."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ops import (
    compute_accumulated_cohort_metrics,
    event_exists,
    is_ordered_seq_present,
    meta_value_operation,
    regex,
)


def _sample_trace() -> dict:
    return {
        "Transcript": [{"user": "I want to pay"}, {"bot": "Payment was successful"}],
        "ordered_events": [
            {"USER_QUERY": {"content": "I want to pay my bill", "event_value": {}}},
            {
                "TOOL_CALL_RESULT": {
                    "Authenticate_Customer": {"tool_args": {}, "result": {"ok": True}}
                }
            },
            {"RESPONSE.FINAL": {"content": "Payment was successful today", "event_value": {}}},
        ],
        "accumulated_events": {
            "RESPONSE.FINAL": {"latency": [100.0, 200.0]},
            "VOICE_SESSION_LATENCY_METRICS": {"tool_call_latency_ms": [1.0, 2.0, 3.0]},
            "TOKEN_USAGE_DETAILS": {"input_tokens": [10, 20]},
        },
    }


class TestOrderedOps(unittest.TestCase):
    def test_event_exists(self) -> None:
        trace = _sample_trace()
        self.assertTrue(event_exists(trace, "USER_QUERY"))
        self.assertTrue(event_exists(trace, "TOOL_CALL_RESULT"))
        self.assertFalse(event_exists(trace, "LLM_INVOCATION_ERROR"))

    def test_meta_value_exists_and_eq(self) -> None:
        trace = _sample_trace()
        self.assertTrue(
            meta_value_operation(
                trace,
                ["TOOL_CALL_RESULT", "Authenticate_Customer"],
                None,
                "exists",
            )
        )
        self.assertTrue(
            meta_value_operation(
                trace,
                ["TOOL_CALL_RESULT", "Authenticate_Customer", "result", "ok"],
                True,
                "==",
            )
        )
        self.assertFalse(
            meta_value_operation(
                trace,
                ["TOOL_CALL_RESULT", "Make_CC_Payment"],
                None,
                "exists",
            )
        )

    def test_regex_turns(self) -> None:
        trace = _sample_trace()
        self.assertTrue(regex(trace, "user_turn", r"\bpay\b"))
        self.assertTrue(regex(trace, "bot_turn", r"successful"))
        self.assertFalse(regex(trace, "bot_turn", r"declined"))

    def test_ordered_seq_auth_before_response(self) -> None:
        trace = _sample_trace()
        self.assertTrue(
            is_ordered_seq_present(
                trace,
                [
                    ("TOOL_CALL_RESULT", ("Authenticate_Customer",), None, "exists"),
                    ("RESPONSE.FINAL",),
                ],
            )
        )
        self.assertFalse(
            is_ordered_seq_present(
                trace,
                [
                    ("RESPONSE.FINAL",),
                    ("TOOL_CALL_RESULT", ("Authenticate_Customer",), None, "exists"),
                ],
            )
        )

    def test_payment_hallucination_pattern(self) -> None:
        trace = _sample_trace()
        bot_success = regex(trace, "bot_turn", r"(?i)(payment was successful|successfully paid)")
        payment_tool = meta_value_operation(
            trace,
            ["TOOL_CALL_RESULT", "Make_CC_Payment"],
            None,
            "exists",
        )
        self.assertTrue(bot_success)
        self.assertFalse(payment_tool)


class TestAccumulatedMetrics(unittest.TestCase):
    def test_pool_and_p95(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            s1 = {
                "ordered_events": [],
                "accumulated_events": {"VOICE_SESSION_LATENCY_METRICS": {"tool_call_latency_ms": [1, 2, 3]}},
            }
            s2 = {
                "ordered_events": [],
                "accumulated_events": {"VOICE_SESSION_LATENCY_METRICS": {"tool_call_latency_ms": [4]}},
            }
            (root / "a.json").write_text(json.dumps(s1))
            (root / "b.json").write_text(json.dumps(s2))

            out = compute_accumulated_cohort_metrics(root)
            m = out["metrics"]["VOICE_SESSION_LATENCY_METRICS.tool_call_latency_ms"]
            self.assertEqual(m["n"], 4)
            self.assertEqual(m["p95"], 4.0)

    def test_token_stats_and_skip_null(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            doc = {
                "ordered_events": [],
                "accumulated_events": {
                    "TOKEN_USAGE_DETAILS": {"input_tokens": [10, None, 20, "bad"]},
                },
            }
            (root / "one.json").write_text(json.dumps(doc))
            out = compute_accumulated_cohort_metrics(root)
            m = out["metrics"]["TOKEN_USAGE_DETAILS.input_tokens"]
            self.assertEqual(m["n"], 2)
            self.assertEqual(m["total"], 30.0)
            self.assertEqual(m["mean"], 15.0)

    def test_transfer_rate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "t.json").write_text(
                json.dumps(
                    {
                        "accumulated_events": {"CALL_TRANSFER_COMPLETED": {"exists": True}},
                        "ordered_events": [],
                    }
                )
            )
            (root / "n.json").write_text(json.dumps({"accumulated_events": {}, "ordered_events": []}))
            out = compute_accumulated_cohort_metrics(root)
            tr = out["metrics"]["CALL_TRANSFER_COMPLETED.exists"]
            self.assertEqual(tr["sessions_total"], 2)
            self.assertEqual(tr["sessions_with_transfer"], 1)
            self.assertEqual(tr["session_rate"], 0.5)


if __name__ == "__main__":
    unittest.main()
