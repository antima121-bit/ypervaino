from __future__ import annotations

import re
from typing import Any

from ypervaino.study_store import StudyStore, now_iso


def _blueprint_root(store: StudyStore):
    root = store.intermediate_dir / "blueprint"
    root.mkdir(parents=True, exist_ok=True)
    (root / "versions").mkdir(parents=True, exist_ok=True)
    return root


def _manifest_path(store: StudyStore):
    return _blueprint_root(store) / "manifest.json"


def _version_path(store: StudyStore, version: str):
    return _blueprint_root(store) / "versions" / f"{version}.json"


def _next_version(manifest: dict[str, Any]) -> str:
    versions = manifest.get("versions") or []
    if not versions:
        return "v0001"
    last = versions[-1]["version"]
    n = int(re.sub(r"\D", "", last) or "0") + 1
    return f"v{n:04d}"


def init_baseline(store: StudyStore, blueprint: dict[str, Any], dialog_flow: dict[str, Any] | None = None) -> str:
    root = _blueprint_root(store)
    manifest_path = _manifest_path(store)
    if manifest_path.exists():
        return store.read_json(manifest_path).get("current_version") or "v0001"

    version = "v0001"
    rel = f"intermediate/blueprint/versions/{version}.json"
    payload = {
        "version": version,
        "created_at": now_iso(),
        "source": "initial_fetch",
        "parent_version": None,
        "source_proposal_id": None,
        "blueprint": blueprint,
        "dialog_flow": dialog_flow,
    }
    store.write_json(_version_path(store, version), payload)
    manifest = {
        "schema_version": "1.0",
        "study_slug": store.slug,
        "current_version": version,
        "baseline_version": version,
        "versions": [{
            "version": version,
            "created_at": payload["created_at"],
            "source": "initial_fetch",
            "parent_version": None,
            "path": rel,
        }],
    }
    store.write_json(manifest_path, manifest)
    if dialog_flow is not None:
        store.write_json(root / "dialog_flow.json", dialog_flow)
    return version


def read_manifest(store: StudyStore) -> dict[str, Any]:
    path = _manifest_path(store)
    if not path.exists():
        return {
            "schema_version": "1.0",
            "study_slug": store.slug,
            "current_version": "v0001",
            "baseline_version": "v0001",
            "versions": [],
        }
    return store.read_json(path)


def current_version(store: StudyStore) -> str:
    return read_manifest(store).get("current_version") or "v0001"


def load_version_doc(store: StudyStore, version: str) -> dict[str, Any]:
    ver = version if version != "current" else current_version(store)
    path = _version_path(store, ver)
    if not path.exists():
        raise FileNotFoundError(f"Blueprint version {ver} not found")
    return store.read_json(path)


def load_blueprint(store: StudyStore, version: str | None = None) -> dict[str, Any]:
    doc = load_version_doc(store, version or "current")
    return doc.get("blueprint") or {}


def load_dialog_flow(store: StudyStore, version: str | None = None) -> dict[str, Any] | None:
    doc = load_version_doc(store, version or "current")
    df = doc.get("dialog_flow")
    if df:
        return df
    df_path = _blueprint_root(store) / "dialog_flow.json"
    if df_path.exists():
        return store.read_json(df_path)
    return None


def append_version(
    store: StudyStore,
    blueprint: dict[str, Any],
    *,
    source: str,
    parent_version: str | None = None,
    source_proposal_id: str | None = None,
    label: str | None = None,
    dialog_flow: dict[str, Any] | None = None,
) -> str:
    manifest = read_manifest(store)
    new_ver = _next_version(manifest)
    rel = f"intermediate/blueprint/versions/{new_ver}.json"
    payload = {
        "version": new_ver,
        "created_at": now_iso(),
        "source": source,
        "parent_version": parent_version or manifest.get("current_version"),
        "source_proposal_id": source_proposal_id,
        "blueprint": blueprint,
        "dialog_flow": dialog_flow,
    }
    store.write_json(_version_path(store, new_ver), payload)
    entry = {
        "version": new_ver,
        "created_at": payload["created_at"],
        "source": source,
        "source_proposal_id": source_proposal_id,
        "parent_version": payload["parent_version"],
        "label": label,
        "path": rel,
    }
    manifest.setdefault("versions", []).append(entry)
    manifest["current_version"] = new_ver
    manifest["baseline_version"] = manifest.get("baseline_version") or "v0001"
    store.write_json(_manifest_path(store), manifest)
    if dialog_flow is not None:
        store.write_json(_blueprint_root(store) / "dialog_flow.json", dialog_flow)
    return new_ver


def ensure_baseline(store: StudyStore, req: dict[str, Any]) -> str:
    """Re-fetch blueprint if baseline missing (older studies)."""
    if _manifest_path(store).exists():
        return current_version(store)
    from ypervaino.data_layer import fetch_blueprint

    bp = fetch_blueprint(req["tenant"], req["assistant_origin_id"], req.get("channel") or "voice")
    df_path = _blueprint_root(store) / "dialog_flow.json"
    dialog_flow = store.read_json(df_path) if df_path.exists() else None
    return init_baseline(store, bp, dialog_flow)
