"""Tests for llm_judge pair loading (no API)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from llm_judge import load_failed_pairs


class TestLlmJudge(unittest.TestCase):
    def test_load_failed_pairs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "hypothesis_eval").mkdir()
            (root / "generated_hypotheses.json").write_text(
                json.dumps(
                    {
                        "hypotheses": [
                            {
                                "hypothesis_id": "h1",
                                "title": "t",
                                "polarity": "negative",
                                "scope_predicate": {},
                                "claim_predicate": {},
                            }
                        ]
                    }
                )
            )
            (root / "hypothesis_eval" / "per_session_id.json").write_text(
                json.dumps(
                    {
                        "sessions": {
                            "s1": {
                                "hypotheses": {
                                    "h1": {
                                        "applicable": True,
                                        "passed": False,
                                    }
                                }
                            },
                            "s2": {
                                "hypotheses": {
                                    "h1": {
                                        "applicable": True,
                                        "passed": True,
                                    }
                                }
                            },
                        }
                    }
                )
            )
            pairs, hyp_by_id = load_failed_pairs(root)
            self.assertEqual(len(pairs), 1)
            self.assertEqual(pairs[0].session_id, "s1")
            self.assertIn("h1", hyp_by_id)


if __name__ == "__main__":
    unittest.main()
