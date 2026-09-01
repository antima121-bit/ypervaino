from __future__ import annotations

import re
from typing import Any

from ypervaino.config_loader import load_artifact_templates, load_primitives, load_semantic_methods
from ypervaino.predicate import parse_predicate


class PlanValidationError(Exception):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


def catalog_primitive_names() -> set[str]:
    """Concrete primitive keys from config/primitives.yaml (excludes parameterized templates)."""
    prims = load_primitives().get("primitives") or {}
    return {name for name in prims if name and not str(name).startswith("{")}


def primitive_catalog_for_prompt() -> list[dict[str, Any]]:
    prims = load_primitives().get("primitives") or {}
    rows: list[dict[str, Any]] = []
    for name, spec in sorted(prims.items()):
        if str(name).startswith("{"):
            continue
        if not isinstance(spec, dict):
            continue
        rows.append({
            "name": name,
            "value_type": spec.get("value_type"),
            "description": (spec.get("description") or "")[:160],
        })
    return rows


def _primitive_names_from_plan(plan: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for p in plan.get("primitives_required") or []:
        if isinstance(p, dict):
            if p.get("name"):
                names.add(str(p["name"]))
        elif p:
            names.add(str(p))
    return names


def _signal_name(sig: dict[str, Any]) -> str | None:
    name = sig.get("name") or sig.get("signal")
    return str(name).strip() if name else None


def _rule_based_has_spec(spec: dict[str, Any]) -> bool:
    return bool(spec.get("keywords") or spec.get("regex"))


def _collect_predicate_var_names(node: Any) -> set[str]:
    node = parse_predicate(node)
    if not isinstance(node, dict):
        return set()
    names: set[str] = set()
    op = (node.get("op") or "").upper()
    if op in ("AND", "OR"):
        for child in node.get("args") or node.get("nodes") or []:
            names |= _collect_predicate_var_names(child)
    elif op in ("CMP", "COMPARISON") or node.get("cmp") or node.get("operator"):
        n = node.get("name")
        if n and n != "_":
            names.add(str(n))
    elif op == "NOT":
        child = (node.get("args") or node.get("nodes") or [None])[0]
        names |= _collect_predicate_var_names(child)
    elif op == "IS_NULL" and node.get("name"):
        names.add(str(node["name"]))
    elif op == "IN" and node.get("name"):
        names.add(str(node["name"]))
    elif op == "BETWEEN" and node.get("name"):
        names.add(str(node["name"]))
    return names


def validate_plan(plan: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    allowed_methods = set((load_semantic_methods().get("methods") or {}).keys())
    plot_templates = set((load_artifact_templates().get("plots") or {}).keys())
    table_templates = set((load_artifact_templates().get("tables") or {}).keys())
    catalog = catalog_primitive_names()

    prim_names = _primitive_names_from_plan(plan)
    signal_names: set[str] = set()
    for sig in plan.get("signals_required") or []:
        sname = _signal_name(sig)
        if sname:
            signal_names.add(sname)

    for pname in sorted(prim_names):
        if pname not in catalog:
            errors.append(f"Unknown primitive (not in primitives.yaml): {pname}")

    for sig in plan.get("signals_required") or []:
        sname = _signal_name(sig)
        method = sig.get("method")
        if not sname:
            errors.append("signals_required entry missing name/signal")
            continue
        if sname in prim_names:
            errors.append(
                f"Signal '{sname}' duplicates primitive '{sname}' — use primitives_required only; "
                "signals_required is for new semantic labels not in the catalog"
            )
        if method and method not in allowed_methods:
            errors.append(f"Unknown semantic method: {method}")
        spec = sig.get("spec") or {}
        if method == "rule_based" and not _rule_based_has_spec(spec):
            errors.append(
                f"rule_based signal '{sname}' missing spec.keywords or spec.regex"
            )
        if method == "intent_classifier" and not (spec.get("intent_id") or spec.get("labels")):
            errors.append(f"intent_classifier signal '{sname}' missing spec.intent_id or spec.labels")
        if method == "embedding_nearest_neighbor" and not (spec.get("labels") or spec.get("prototypes")):
            errors.append(f"embedding_nearest_neighbor signal '{sname}' missing spec.labels or spec.prototypes")
        for pat in spec.get("regex") or []:
            try:
                re.compile(pat, re.I)
            except re.error as e:
                errors.append(f"Invalid regex in signal {sname}: {e}")

    for aspect in (plan.get("quantitative") or {}).get("aspects") or []:
        for comp in aspect.get("components") or []:
            ref = comp.get("ref") or {}
            if (ref.get("kind") or "").strip() == "primitive":
                ref_name = (ref.get("name") or "").strip()
                if ref_name and ref_name not in catalog:
                    errors.append(f"Aspect '{aspect.get('id')}' references unknown primitive: {ref_name}")

    allowed_predicate_names = prim_names | signal_names

    for hyp in ((plan.get("qualitative") or {}).get("hypotheses") or []):
        pred = hyp.get("predicate")
        if pred is None:
            continue
        for name in _collect_predicate_var_names(pred):
            if name not in allowed_predicate_names:
                errors.append(
                    f"Hypothesis '{hyp.get('id')}' predicate references '{name}' "
                    f"not in primitives_required or signals_required"
                )

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
