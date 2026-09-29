"""Evaluate generated hypotheses on parsed_traces with per-op debug traces."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ops import (
    compute_accumulated_cohort_metrics,
    event_exists,
    is_ordered_seq_present,
    meta_value_operation,
    regex,
)

logger = logging.getLogger(__name__)

HYPOTHESIS_EVAL_DIR = "hypothesis_eval"
PER_HYPOTHESIS_FILENAME = "per_hypothesis.json"
PER_SESSION_FILENAME = "per_session_id.json"


def _eval_leaf(parsed_trace: dict[str, Any], node: dict[str, Any]) -> tuple[bool, str | None]:
    op = node["op"]
    try:
        if op == "event_exists":
            return event_exists(parsed_trace, node["event_name"]), None
        if op == "meta_value_operation":
            value = node.get("value")
            compare = node.get("compare_op", "exists")
            return meta_value_operation(parsed_trace, node["path"], value, compare), None
        if op == "regex":
            return regex(parsed_trace, node["turn_type"], node["pattern"]), None
        if op == "is_ordered_seq_present":
            return is_ordered_seq_present(parsed_trace, node["sequences"]), None
        raise ValueError(f"Unknown predicate op: {op!r}")
    except Exception as exc:
        return False, str(exc)


def _node_summary(node: dict[str, Any]) -> dict[str, Any]:
    op = node.get("op")
    if op == "event_exists":
        return {"event_name": node.get("event_name")}
    if op == "meta_value_operation":
        return {"path": node.get("path"), "compare_op": node.get("compare_op"), "value": node.get("value")}
    if op == "regex":
        return {"turn_type": node.get("turn_type"), "pattern": node.get("pattern")}
    if op == "is_ordered_seq_present":
        return {"sequences": node.get("sequences")}
    if op in {"and", "or", "not"}:
        return {"composite": op}
    return {"raw_op": op}


def eval_predicate_with_trace(
    parsed_trace: dict[str, Any],
    node: dict[str, Any],
    *,
    path: str = "root",
) -> tuple[bool, list[dict[str, Any]]]:
    """Return (boolean result, flat list of op evaluations for debugging)."""
    if not isinstance(node, dict) or "op" not in node:
        raise ValueError(f"Invalid predicate node at {path}")

    op = node["op"]
    trace: list[dict[str, Any]] = []

    if op in {"event_exists", "meta_value_operation", "regex", "is_ordered_seq_present"}:
        passed, eval_error = _eval_leaf(parsed_trace, node)
        entry: dict[str, Any] = {
            "path": path,
            "op": op,
            "passed": passed,
            "detail": _node_summary(node),
        }
        if eval_error:
            entry["error"] = eval_error
        trace.append(entry)
        return passed, trace

    if op == "and":
        operand_results: list[bool] = []
        for idx, child in enumerate(node.get("operands") or []):
            child_result, child_trace = eval_predicate_with_trace(
                parsed_trace, child, path=f"{path}.and[{idx}]"
            )
            trace.extend(child_trace)
            operand_results.append(child_result)
        passed = all(operand_results) if operand_results else False
        trace.append(
            {
                "path": path,
                "op": "and",
                "passed": passed,
                "detail": {"operand_results": operand_results},
            }
        )
        return passed, trace

    if op == "or":
        operand_results = []
        for idx, child in enumerate(node.get("operands") or []):
            child_result, child_trace = eval_predicate_with_trace(
                parsed_trace, child, path=f"{path}.or[{idx}]"
            )
            trace.extend(child_trace)
            operand_results.append(child_result)
        passed = any(operand_results) if operand_results else False
        trace.append(
            {
                "path": path,
                "op": "or",
                "passed": passed,
                "detail": {"operand_results": operand_results},
            }
        )
        return passed, trace

    if op == "not":
        child = node.get("operand")
        if not isinstance(child, dict):
            raise ValueError(f"not operand missing at {path}")
        child_result, child_trace = eval_predicate_with_trace(parsed_trace, child, path=f"{path}.not")
        trace.extend(child_trace)
        passed = not child_result
        trace.append({"path": path, "op": "not", "passed": passed, "detail": {"operand_result": child_result}})
        return passed, trace

    raise ValueError(f"Unknown predicate op at {path}: {op!r}")


def _session_passed(*, polarity: str, claim_matched: bool) -> bool:
    if polarity == "positive":
        return claim_matched
    if polarity == "negative":
        return not claim_matched
    raise ValueError(f"Unknown polarity: {polarity!r}")


def evaluate_hypothesis_on_session(
    parsed_trace: dict[str, Any],
    hypothesis: dict[str, Any],
) -> dict[str, Any]:
    hyp_id = hypothesis["hypothesis_id"]
    polarity = hypothesis["polarity"]
    scope_result, scope_trace = eval_predicate_with_trace(
        parsed_trace, hypothesis["scope_predicate"], path=f"{hyp_id}.scope"
    )
    claim_result, claim_trace = eval_predicate_with_trace(
        parsed_trace, hypothesis["claim_predicate"], path=f"{hyp_id}.claim"
    )
    applicable = scope_result
    claim_matched = claim_result if applicable else False
    passed = _session_passed(polarity=polarity, claim_matched=claim_matched) if applicable else False

    return {
        "hypothesis_id": hyp_id,
        "applicable": applicable,
        "claim_matched": claim_matched,
        "passed": passed,
        "polarity": polarity,
        "scope_eval": {"result": scope_result, "operations": scope_trace},
        "claim_eval": {"result": claim_result, "operations": claim_trace},
    }


def run_hypothesis_evaluation(study_dir: Path | str) -> dict[str, Path]:
    study_path = Path(study_dir)
    parsed_dir = study_path / "parsed_traces"
    hypotheses_path = study_path / "generated_hypotheses.json"
    if not hypotheses_path.is_file():
        raise FileNotFoundError(f"Missing generated hypotheses: {hypotheses_path}")
    if not parsed_dir.is_dir():
        raise NotADirectoryError(f"Missing parsed_traces: {parsed_dir}")

    doc = json.loads(hypotheses_path.read_text(encoding="utf-8"))
    hypotheses: list[dict[str, Any]] = doc.get("hypotheses") or []
    if not hypotheses:
        raise ValueError("generated_hypotheses.json has empty hypotheses list")

    out_dir = study_path / HYPOTHESIS_EVAL_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    accumulated = compute_accumulated_cohort_metrics(parsed_dir)

    per_hypothesis: dict[str, Any] = {
        "meta": {
            "study_dir": str(study_path),
            "parsed_traces_dir": str(parsed_dir),
            "hypothesis_count": len(hypotheses),
        },
        "accumulated_cohort_metrics": accumulated,
        "hypotheses": {},
    }
    per_session: dict[str, Any] = {"meta": {"study_dir": str(study_path)}, "sessions": {}}

    for hyp in hypotheses:
        hid = hyp["hypothesis_id"]
        per_hypothesis["hypotheses"][hid] = {
            "hypothesis_id": hid,
            "title": hyp.get("title"),
            "polarity": hyp.get("polarity"),
            "n_applicable": 0,
            "n_matched": 0,
            "match_rate": None,
            "scoped_session_ids": [],
            "passed_session_ids": [],
            "failed_session_ids": [],
        }

    for path in sorted(parsed_dir.glob("*.json")):
        session_id = path.stem
        parsed_trace = json.loads(path.read_text(encoding="utf-8"))
        session_record: dict[str, Any] = {"hypotheses": {}}

        for hyp in hypotheses:
            hid = hyp["hypothesis_id"]
            result = evaluate_hypothesis_on_session(parsed_trace, hyp)
            session_record["hypotheses"][hid] = result

            agg = per_hypothesis["hypotheses"][hid]
            if result["applicable"]:
                agg["n_applicable"] += 1
                agg["scoped_session_ids"].append(session_id)
                if result["claim_matched"]:
                    agg["n_matched"] += 1
                if result["passed"]:
                    agg["passed_session_ids"].append(session_id)
                else:
                    agg["failed_session_ids"].append(session_id)

        per_session["sessions"][session_id] = session_record

    for hid, agg in per_hypothesis["hypotheses"].items():
        n = agg["n_applicable"]
        agg["match_rate"] = (agg["n_matched"] / n) if n else None

    hyp_path = out_dir / PER_HYPOTHESIS_FILENAME
    sess_path = out_dir / PER_SESSION_FILENAME
    hyp_path.write_text(json.dumps(per_hypothesis, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    sess_path.write_text(json.dumps(per_session, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    logger.info("Hypothesis eval written to %s and %s", hyp_path, sess_path)
    return {"per_hypothesis": hyp_path, "per_session_id": sess_path}
