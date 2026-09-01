from __future__ import annotations

import difflib
import re
from typing import Any

from ypervaino.blueprint_patch import apply_patch
from ypervaino.blueprint_store import (
    append_version,
    current_version,
    load_blueprint,
    load_dialog_flow,
    load_version_doc,
    read_manifest,
)
from ypervaino.proposal_generator import _bundle_path, read_generation_status
from ypervaino.proposal_validate import normalize_patch, normalize_shallow_proposal
from ypervaino.study_store import StudyStore, now_iso


class ProposalError(Exception):
    def __init__(self, code: str, message: str, status: int = 409, extra: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.extra = extra or {}


def _require_complete(store: StudyStore) -> dict[str, Any]:
    meta = store.read_meta()
    if meta.get("status") != "complete":
        raise ProposalError("INVALID_STATE", f"Study must be complete (got {meta.get('status')})", 409)
    return meta


def load_bundle(store: StudyStore) -> dict[str, Any] | None:
    path = _bundle_path(store)
    if not path.exists():
        return None
    return store.read_json(path)


def save_bundle(store: StudyStore, bundle: dict[str, Any]) -> None:
    store.write_json(_bundle_path(store), bundle)


def _find_shallow(bundle: dict, proposal_id: str) -> dict[str, Any] | None:
    for p in bundle.get("shallow_proposals") or []:
        if p.get("id") == proposal_id:
            return p
    return None


def _find_deep(bundle: dict, proposal_id: str) -> dict[str, Any] | None:
    for p in bundle.get("deep_proposals") or []:
        if p.get("id") == proposal_id:
            return p
    return None


def _applied_target_keys(bundle: dict) -> set[str]:
    keys: set[str] = set()
    for p in bundle.get("shallow_proposals") or []:
        if p.get("status") == "applied" and p.get("target_key"):
            keys.add(p["target_key"])
    return keys


def get_proposals_payload(store: StudyStore) -> dict[str, Any]:
    meta = _require_complete(store)
    gen = read_generation_status(store)
    bundle = load_bundle(store) if gen.get("status") == "ready" else None
    cur = current_version(store)
    return {
        "meta": {
            "title": meta.get("title"),
            "slug": store.slug,
            "status": meta.get("status"),
        },
        "generation": {
            "status": gen.get("status", "not_started"),
            "started_at": gen.get("started_at"),
            "finished_at": gen.get("finished_at"),
            "error": gen.get("error"),
            "logs_url": f"/api/v1/ypervaino/studies/{store.slug}/logs?tail=100",
        },
        "bundle": bundle,
        "blueprint": {
            "current_version": cur,
            "manifest_url": f"/api/v1/ypervaino/studies/{store.slug}/blueprint/manifest",
        },
    }


def start_generation(store: StudyStore, *, force: bool = False) -> dict[str, Any]:
    _require_complete(store)
    gen = read_generation_status(store)
    status = gen.get("status", "not_started")
    if status == "generating":
        return {
            "slug": store.slug,
            "generation": {
                "status": "generating",
                "started_at": gen.get("started_at"),
                "poll_url": f"/api/v1/ypervaino/studies/{store.slug}/proposals",
            },
        }
    if status == "ready" and not force:
        return get_proposals_payload(store)
    return {
        "slug": store.slug,
        "generation": {
            "status": "generating",
            "started_at": now_iso(),
            "poll_url": f"/api/v1/ypervaino/studies/{store.slug}/proposals",
        },
    }


def apply_shallow_proposal(store: StudyStore, proposal_id: str) -> dict[str, Any]:
    _require_complete(store)
    gen = read_generation_status(store)
    if gen.get("status") != "ready":
        raise ProposalError("INVALID_STATE", "Proposals not ready", 409)
    bundle = load_bundle(store)
    if not bundle:
        raise ProposalError("NOT_FOUND", "Proposal bundle missing", 404)
    proposal = _find_shallow(bundle, proposal_id)
    if not proposal:
        raise ProposalError("NOT_FOUND", f"Shallow proposal {proposal_id} not found", 404)
    if proposal.get("status") != "pending":
        raise ProposalError("PROPOSAL_NOT_PENDING", f"Proposal status is {proposal.get('status')}", 409)
    target_key = proposal.get("target_key")
    if target_key and target_key in _applied_target_keys(bundle):
        raise ProposalError("PROPOSAL_CONFLICT", f"target_key {target_key} already applied", 409)

    prev_ver = current_version(store)
    blueprint = load_blueprint(store)
    dialog_flow = load_dialog_flow(store)
    patch = normalize_patch(proposal.get("patch"))
    target = proposal.get("target") or {}

    new_bp, new_df, errors = apply_patch(blueprint, patch, target, dialog_flow, dry_run=False)
    if errors:
        raise ProposalError(
            "APPLY_FAILED",
            "Patch could not be applied",
            409,
            {"apply_result": {"success": False, "errors": errors}},
        )

    new_ver = append_version(
        store,
        new_bp,
        source="proposal_apply",
        parent_version=prev_ver,
        source_proposal_id=proposal_id,
        label=proposal.get("title"),
        dialog_flow=new_df,
    )
    proposal["status"] = "applied"
    proposal["applied_at"] = now_iso()
    proposal["applied_version"] = new_ver
    save_bundle(store, bundle)
    manifest = read_manifest(store)
    ops_count = len(patch.get("ops") or [])
    return {
        "proposal_id": proposal_id,
        "proposal_status": "applied",
        "applied_at": proposal["applied_at"],
        "blueprint": {
            "previous_version": prev_ver,
            "new_version": new_ver,
            "manifest": manifest,
        },
        "apply_result": {
            "success": True,
            "ops_applied": ops_count,
            "warnings": [],
        },
    }


def reject_proposal(store: StudyStore, proposal_id: str, reason: str | None = None) -> dict[str, Any]:
    _require_complete(store)
    bundle = load_bundle(store)
    if not bundle:
        raise ProposalError("NOT_FOUND", "Proposal bundle missing", 404)
    proposal = _find_shallow(bundle, proposal_id) or _find_deep(bundle, proposal_id)
    if not proposal:
        raise ProposalError("NOT_FOUND", f"Proposal {proposal_id} not found", 404)
    if proposal.get("status") not in ("pending",):
        raise ProposalError("PROPOSAL_NOT_PENDING", f"Proposal status is {proposal.get('status')}", 409)
    proposal["status"] = "rejected"
    proposal["rejected_at"] = now_iso()
    if reason:
        proposal["reject_reason"] = reason
    save_bundle(store, bundle)
    return {"proposal_id": proposal_id, "proposal_status": "rejected"}


def acknowledge_proposal(store: StudyStore, proposal_id: str) -> dict[str, Any]:
    _require_complete(store)
    bundle = load_bundle(store)
    if not bundle:
        raise ProposalError("NOT_FOUND", "Proposal bundle missing", 404)
    proposal = _find_deep(bundle, proposal_id)
    if not proposal:
        raise ProposalError("NOT_FOUND", f"Deep proposal {proposal_id} not found", 404)
    if proposal.get("status") != "pending":
        raise ProposalError("PROPOSAL_NOT_PENDING", f"Proposal status is {proposal.get('status')}", 409)
    proposal["status"] = "acknowledged"
    proposal["acknowledged_at"] = now_iso()
    save_bundle(store, bundle)
    return {"proposal_id": proposal_id, "proposal_status": "acknowledged"}


def jira_stub(store: StudyStore, proposal_id: str) -> dict[str, Any]:
    _require_complete(store)
    bundle = load_bundle(store)
    if not bundle:
        raise ProposalError("NOT_FOUND", "Proposal bundle missing", 404)
    proposal = _find_deep(bundle, proposal_id)
    if not proposal:
        raise ProposalError("NOT_FOUND", f"Deep proposal {proposal_id} not found", 404)
    session_ids: list[str] = []
    for ev in proposal.get("evidence") or []:
        session_ids.extend(ev.get("session_ids") or [])
    session_ids = list(dict.fromkeys(session_ids))[:5]
    desc_parts = [
        proposal.get("description") or "",
        "",
        f"**Recommendation:** {proposal.get('recommendation') or ''}",
        f"**Out of scope reason:** {proposal.get('out_of_scope_reason') or ''}",
        "",
        f"Study: {store.slug}",
    ]
    if proposal.get("suggested_approach"):
        desc_parts.insert(2, f"**Suggested approach:** {proposal['suggested_approach']}")
    return {
        "proposal_id": proposal_id,
        "stub": True,
        "ticket_draft": {
            "summary": proposal.get("title") or proposal_id,
            "description": "\n".join(desc_parts),
            "labels": ["ypervaino", "voice-bot"],
            "study_slug": store.slug,
            "evidence_session_ids": session_ids,
        },
        "message": "Jira integration not configured; copy draft to create ticket manually.",
    }


def manual_blueprint_patch(
    store: StudyStore,
    target: dict[str, Any],
    patch: dict[str, Any] | list[Any],
    note: str | None = None,
) -> dict[str, Any]:
    _require_complete(store)
    prev_ver = current_version(store)
    blueprint = load_blueprint(store)
    dialog_flow = load_dialog_flow(store)
    patch = normalize_patch(patch)
    new_bp, new_df, errors = apply_patch(blueprint, patch, target, dialog_flow, dry_run=False)
    if errors:
        raise ProposalError(
            "APPLY_FAILED",
            "Patch could not be applied",
            409,
            {"apply_result": {"success": False, "errors": errors}},
        )
    new_ver = append_version(
        store,
        new_bp,
        source="manual_edit",
        parent_version=prev_ver,
        label=note,
        dialog_flow=new_df,
    )
    manifest = read_manifest(store)
    return {
        "blueprint": {
            "previous_version": prev_ver,
            "new_version": new_ver,
            "manifest": manifest,
            "source": "manual_edit",
        },
        "apply_result": {
            "success": True,
            "ops_applied": len(patch.get("ops") or []),
            "warnings": [],
        },
    }


def _target_from_key(target_key: str) -> dict[str, Any]:
    """Best-effort BlueprintTarget from target_key for diff."""
    if target_key.startswith("skill:"):
        parts = target_key.split(":")
        if len(parts) >= 3:
            return {
                "domain": "skill.instructions",
                "skill_name": parts[1],
                "field_path": parts[2],
                "display_label": f"{parts[1]} › {parts[2]}",
            }
    if target_key.startswith("global:"):
        return {"domain": "global_guidelines", "display_label": "Global guidelines", "field_path": "guidelines_and_rules"}
    if target_key.startswith("tool:"):
        parts = target_key.split(":")
        if len(parts) >= 3:
            return {
                "domain": "tool.description",
                "tool_name": parts[1],
                "field_path": parts[2],
                "display_label": f"{parts[1]} › {parts[2]}",
            }
    return {"domain": "global_guidelines", "display_label": target_key, "field_path": "guidelines_and_rules"}


def blueprint_diff(
    store: StudyStore,
    from_version: str,
    to_version: str,
    target_key: str,
) -> dict[str, Any]:
    target = _target_from_key(target_key)
    from_doc = load_version_doc(store, from_version)
    to_doc = load_version_doc(store, to_version)
    from_bp = from_doc.get("blueprint") or {}
    to_bp = to_doc.get("blueprint") or {}
    from_df = from_doc.get("dialog_flow")
    to_df = to_doc.get("dialog_flow")

    from ypervaino.blueprint_patch import _get_text

    before = _get_text(from_bp, from_df, target)
    after = _get_text(to_bp, to_df, target)
    unified = "\n".join(difflib.unified_diff(
        before.splitlines(),
        after.splitlines(),
        fromfile=from_version,
        tofile=to_version,
        lineterm="",
    ))
    excerpt_len = 500
    return {
        "from_version": from_version,
        "to_version": to_version,
        "target_key": target_key,
        "before_excerpt": before[:excerpt_len],
        "after_excerpt": after[:excerpt_len],
        "unified_diff": unified,
    }


def get_blueprint_version(store: StudyStore, version: str) -> dict[str, Any]:
    doc = load_version_doc(store, version)
    return {
        "version": doc.get("version"),
        "created_at": doc.get("created_at"),
        "source": doc.get("source"),
        "source_proposal_id": doc.get("source_proposal_id"),
        "parent_version": doc.get("parent_version"),
        "blueprint": doc.get("blueprint") or {},
        "dialog_flow": doc.get("dialog_flow"),
    }
