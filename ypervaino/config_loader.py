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


def load_semantic_methods() -> dict[str, Any]:
    return _read_yaml("semantic_methods.yaml")


def load_artifact_templates() -> dict[str, Any]:
    return _read_yaml("artifact_templates.yaml")


def load_event_schema() -> dict[str, Any]:
    with (CONFIG_DIR / "event_schema.json").open() as f:
        return json.load(f)
