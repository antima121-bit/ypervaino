"""End-of-run summary from hypothesis eval and LLM judge artifacts."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _count_llm_judge_failures(judge_hypotheses: dict[str, Any], hypothesis_id: str) -> int:
    by_session = judge_hypotheses.get(hypothesis_id) or {}
    if not isinstance(by_session, dict):
        return 0
    return sum(1 for outcome in by_session.values() if (outcome or {}).get("result") == "fail")


def build_pipeline_summary(study_dir: Path | str, *, n_samples: int) -> dict[str, Any]:
    study_path = Path(study_dir)
    summary: dict[str, Any] = {
        "n_samples": n_samples,
        "hypotheses": [],
    }

    per_hyp_path = study_path / "hypothesis_eval" / "per_hypothesis.json"
    if not per_hyp_path.is_file():
        summary["hypothesis_eval"] = "not_run"
        return summary

    per_hyp_doc = json.loads(per_hyp_path.read_text(encoding="utf-8"))
    judge_doc: dict[str, Any] | None = None
    judge_path = study_path / "hypothesis_eval" / "llm_judge_results.json"
    if judge_path.is_file():
        judge_doc = json.loads(judge_path.read_text(encoding="utf-8"))
    judge_hypotheses = (judge_doc or {}).get("hypotheses") or {}

    for hid, agg in sorted((per_hyp_doc.get("hypotheses") or {}).items()):
        failed_ids = agg.get("failed_session_ids") or []
        entry = {
            "hypothesis_id": hid,
            "title": agg.get("title"),
            "n_applicable": int(agg.get("n_applicable") or 0),
            "rule_engine_failed": len(failed_ids),
            "llm_judge_failed": _count_llm_judge_failures(judge_hypotheses, hid),
        }
        if judge_doc is None:
            entry["llm_judge_failed"] = None
        summary["hypotheses"].append(entry)

    summary["hypothesis_eval"] = "ok"
    summary["llm_judge"] = "ok" if judge_doc is not None else "not_run"
    return summary


def log_pipeline_summary(study_dir: Path | str, *, n_samples: int) -> dict[str, Any]:
    """Log a compact debug summary after the pipeline finishes."""
    summary = build_pipeline_summary(study_dir, n_samples=n_samples)

    logger.info("——— Pipeline summary ———")
    logger.info("Samples (parsed sessions): %s", summary["n_samples"])

    if summary.get("hypothesis_eval") == "not_run":
        logger.info("Hypothesis evaluation was not run (no generated hypotheses).")
        logger.info("—————————————————————————")
        return summary

    for row in summary["hypotheses"]:
        title = row.get("title") or row["hypothesis_id"]
        llm_failed = row["llm_judge_failed"]
        if llm_failed is None:
            llm_line = "llm_judge_failed=n/a (judge not run)"
        else:
            llm_line = f"llm_judge_failed={llm_failed}"
        logger.info(
            "Hypothesis %s — %s | applicable=%s | rule_engine_failed=%s | %s",
            row["hypothesis_id"],
            title,
            row["n_applicable"],
            row["rule_engine_failed"],
            llm_line,
        )

    if summary.get("llm_judge") == "not_run":
        logger.info("LLM judge was not run.")

    logger.info("—————————————————————————")
    return summary
