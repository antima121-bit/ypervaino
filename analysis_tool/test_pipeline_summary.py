import json
from pathlib import Path

from pipeline_summary import build_pipeline_summary


def test_build_pipeline_summary(tmp_path: Path):
    study = tmp_path / "uown_study_test"
    (study / "hypothesis_eval").mkdir(parents=True)
    (study / "hypothesis_eval" / "per_hypothesis.json").write_text(
        json.dumps(
            {
                "hypotheses": {
                    "h1": {
                        "title": "Payment flow",
                        "n_applicable": 3,
                        "failed_session_ids": ["s1", "s2"],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    (study / "hypothesis_eval" / "llm_judge_results.json").write_text(
        json.dumps(
            {
                "hypotheses": {
                    "h1": {
                        "s1": {"result": "fail", "description": "x"},
                        "s2": {"result": "pass", "description": "y"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    summary = build_pipeline_summary(study, n_samples=5)
    assert summary["n_samples"] == 5
    assert len(summary["hypotheses"]) == 1
    row = summary["hypotheses"][0]
    assert row["n_applicable"] == 3
    assert row["rule_engine_failed"] == 2
    assert row["llm_judge_failed"] == 1
