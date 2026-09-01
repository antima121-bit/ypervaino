from __future__ import annotations

import re
from typing import Any

from ypervaino.config_loader import load_artifact_templates, load_semantic_methods


class PlanValidationError(Exception):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


def validate_plan(plan: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    allowed_methods = set((load_semantic_methods().get("methods") or {}).keys())
    plot_templates = set((load_artifact_templates().get("plots") or {}).keys())
    table_templates = set((load_artifact_templates().get("tables") or {}).keys())

    signal_names = {s.get("name") for s in (plan.get("signals_required") or []) if s.get("name")}
    prim_names = set()
    for p in plan.get("primitives_required") or []:
        if isinstance(p, dict):
            prim_names.add(p.get("name"))
        else:
            prim_names.add(p)

    for sig in plan.get("signals_required") or []:
        method = sig.get("method")
        if method and method not in allowed_methods:
            errors.append(f"Unknown semantic method: {method}")
        spec = sig.get("spec") or {}
        for pat in spec.get("regex") or []:
            try:
                re.compile(pat, re.I)
            except re.error as e:
                errors.append(f"Invalid regex in signal {sig.get('name')}: {e}")

    allowed_names = signal_names | prim_names | {"opening_intent_class", "turn_count", "session_outcome"}

    def walk(node: Any):
        if not isinstance(node, dict):
            return
        if node.get("op") in ("cmp", "CMP", "COMPARISON") or node.get("cmp"):
            n = node.get("name")
            if n and n not in allowed_names:
                errors.append(f"Predicate references unknown name: {n}")
        for child in node.get("args") or node.get("nodes") or []:
            walk(child)

    for hyp in ((plan.get("qualitative") or {}).get("hypotheses") or []):
        walk(hyp.get("predicate"))

    for plot in ((plan.get("quantitative") or {}).get("suggested_plots") or []):
        tpl = plot.get("template")
        if tpl and tpl not in plot_templates:
            errors.append(f"Unknown plot template: {tpl}")
    for table in ((plan.get("quantitative") or {}).get("suggested_tables") or []):
        tpl = table.get("template")
        if tpl and tpl not in table_templates:
            errors.append(f"Unknown table template: {tpl}")

    return errors


def validate_or_raise(plan: dict[str, Any]) -> None:
    errors = validate_plan(plan)
    if errors:
        raise PlanValidationError(errors)
