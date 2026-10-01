"""Build JSON payload for the results dashboard from a completed study directory."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pipeline_summary import build_pipeline_summary


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_dashboard(study_dir: Path, *, n_samples: int | None = None) -> dict[str, Any]:
    if n_samples is None:
        timings_path = study_dir / "step_timings.json"
        if timings_path.is_file():
            timings = _read_json(timings_path)
            n_samples = int(timings.get("parsed_session_count") or 0)
        else:
            parsed = study_dir / "parsed_traces"
            n_samples = len(list(parsed.glob("*.json"))) if parsed.is_dir() else 0
    summary = build_pipeline_summary(study_dir, n_samples=n_samples)
    lines = [
        "——— Pipeline summary ———",
        f"Samples (parsed sessions): {summary['n_samples']}",
    ]
    if summary.get("hypothesis_eval") == "not_run":
        lines.append("Hypothesis evaluation was not run.")
    else:
        for row in summary.get("hypotheses") or []:
            title = row.get("title") or row["hypothesis_id"]
            llm_failed = row["llm_judge_failed"]
            llm_part = "n/a" if llm_failed is None else str(llm_failed)
            lines.append(
                f"Hypothesis {row['hypothesis_id']} — {title} | "
                f"applicable={row['n_applicable']} | "
                f"rule_engine_failed={row['rule_engine_failed']} | "
                f"llm_judge_failed={llm_part}"
            )
    lines.append("—————————————————————————")
    return {"summary_lines": lines, "pipeline_summary": summary}


def load_rule_engine_results(study_dir: Path) -> dict[str, Any]:
    path = study_dir / "hypothesis_eval" / "per_hypothesis.json"
    if not path.is_file():
        return {"hypotheses": []}
    doc = _read_json(path)
    out: list[dict[str, Any]] = []
    for hid, agg in sorted((doc.get("hypotheses") or {}).items()):
        out.append(
            {
                "hypothesis_id": hid,
                "title": agg.get("title"),
                "failed_session_ids": list(agg.get("failed_session_ids") or []),
            }
        )
    return {"hypotheses": out}


def load_llm_judge_results(study_dir: Path) -> dict[str, Any]:
    path = study_dir / "hypothesis_eval" / "llm_judge_results.json"
    hyp_path = study_dir / "generated_hypotheses.json"
    titles: dict[str, str] = {}
    if hyp_path.is_file():
        hyp_doc = _read_json(hyp_path)
        for h in hyp_doc.get("hypotheses") or []:
            if h.get("hypothesis_id"):
                titles[h["hypothesis_id"]] = h.get("title") or h["hypothesis_id"]

    if not path.is_file():
        return {"hypotheses": []}

    doc = _read_json(path)
    hypotheses_out: list[dict[str, Any]] = []
    for hid, by_session in sorted((doc.get("hypotheses") or {}).items()):
        failed: list[dict[str, str]] = []
        passed: list[dict[str, str]] = []
        if isinstance(by_session, dict):
            for session_id, outcome in sorted(by_session.items()):
                if not isinstance(outcome, dict):
                    continue
                row = {
                    "session_id": session_id,
                    "description": outcome.get("description") or "",
                }
                if outcome.get("result") == "fail":
                    failed.append(row)
                elif outcome.get("result") == "pass":
                    passed.append(row)
        hypotheses_out.append(
            {
                "hypothesis_id": hid,
                "title": titles.get(hid, hid),
                "failed": failed,
                "passed": passed,
            }
        )
    return {"hypotheses": hypotheses_out}


def load_information(study_dir: Path) -> dict[str, Any]:
    path = study_dir / "generated_hypotheses.json"
    if not path.is_file():
        return {"hypotheses": None, "raw": None}
    doc = _read_json(path)
    return {"hypotheses": doc.get("hypotheses"), "raw": doc}


def load_full_results(study_dir: Path) -> dict[str, Any]:
    study_path = Path(study_dir)
    dashboard = load_dashboard(study_path)
    return {
        "dashboard": dashboard,
        "rule_engine": load_rule_engine_results(study_path),
        "llm_judge": load_llm_judge_results(study_path),
        "information": load_information(study_path),
    }
