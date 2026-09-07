from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from ypervaino.settings import CONFIG_DIR


def _read_yaml(name: str) -> dict[str, Any]:
    path = CONFIG_DIR / name
    with path.open() as f:
        return yaml.safe_load(f) or {}


def load_system_knowledge() -> dict[str, Any]:
    return _read_yaml("system_knowledge.yaml")


def load_filter_atoms() -> list[dict[str, Any]]:
    return _read_yaml("filter_atoms.yaml").get("atoms", [])


def load_primitives() -> dict[str, Any]:
    return _read_yaml("primitives.yaml")


def _format_event_type(source: dict[str, Any] | None) -> str:
    if not source:
        return "—"
    event_type = source.get("event_type")
    if isinstance(event_type, list):
        return ", ".join(str(x) for x in event_type)
    if event_type:
        return str(event_type)
    return "—"


def primitive_event_map() -> dict[str, str]:
    """Map primitive name → primary BotProbe event type(s) for UI display."""
    catalog = load_primitives().get("primitives") or {}
    templates: dict[str, dict[str, Any]] = {
        name: spec for name, spec in catalog.items() if isinstance(spec, dict)
    }

    def resolve_source(spec: dict[str, Any]) -> dict[str, Any]:
        direct = spec.get("source")
        if direct:
            return direct
        alias = spec.get("alias_of")
        purpose = spec.get("purpose")
        if alias and isinstance(templates.get(alias), dict):
            tmpl = templates[alias]
            if tmpl.get("source"):
                return tmpl["source"]
        if alias and purpose:
            concrete = alias.replace("{purpose}", str(purpose))
            peer = templates.get(concrete)
            if isinstance(peer, dict):
                return resolve_source(peer)
        return {}

    out: dict[str, str] = {}
    for name, spec in catalog.items():
        if not isinstance(spec, dict) or str(name).startswith("{"):
            continue
        out[name] = _format_event_type(resolve_source(spec))
    return out


def signal_method_map(plan: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for sig in plan.get("signals_required") or []:
        name = sig.get("name") or sig.get("signal")
        if name:
            out[str(name)] = str(sig.get("method") or "signal")
    return out


def load_semantic_methods() -> dict[str, Any]:
    return _read_yaml("semantic_methods.yaml")


def load_artifact_templates() -> dict[str, Any]:
    return _read_yaml("artifact_templates.yaml")


def load_event_schema() -> dict[str, Any]:
    with (CONFIG_DIR / "event_schema.json").open() as f:
        return json.load(f)
