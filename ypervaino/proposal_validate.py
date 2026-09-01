from __future__ import annotations

import uuid
from typing import Any

from ypervaino.blueprint_patch import apply_patch
from ypervaino.blueprint_store import load_blueprint, load_dialog_flow


def normalize_op(op: Any) -> dict[str, Any] | None:
    if not isinstance(op, dict):
        return None
    o = dict(op)
    kind = o.get("op")
    if kind == "replace_text":
        if "find" not in o and "search" in o:
            o["find"] = o.pop("search")
        if "replace" not in o and "replacement" in o:
            o["replace"] = o.pop("replacement")
        if "find" not in o or "replace" not in o:
            return None
    if kind in ("insert_after", "insert_before") and ("anchor" not in o or "text" not in o):
        return None
    if kind == "delete_text" and "find" not in o:
        return None
    if kind in ("replace_field", "append", "prepend") and "value" not in o:
        return None
    if not kind:
        return None
    return o


def normalize_patch(raw: Any) -> dict[str, Any]:
    """Coerce LLM output into BlueprintPatch shape: { ops: PatchOp[], preview? }."""
    if raw is None:
        return {"ops": []}
    if isinstance(raw, list):
        ops = [n for op in raw if (n := normalize_op(op))]
        return {"ops": ops}
    if not isinstance(raw, dict):
        return {"ops": []}
    preview = raw.get("preview")
    if isinstance(raw.get("ops"), list):
        ops = [n for op in raw["ops"] if (n := normalize_op(op))]
        out = {"ops": ops}
        if preview:
            out["preview"] = preview
        return out
    if isinstance(raw.get("ops"), dict):
        n = normalize_op(raw["ops"])
        return {"ops": [n] if n else [], **({"preview": preview} if preview else {})}
    n = normalize_op(raw) if raw.get("op") else None
    if n:
        return {"ops": [n], **({"preview": preview} if preview else {})}
    for key in ("operations", "changes", "patch_ops"):
        if isinstance(raw.get(key), list):
            ops = [n for op in raw[key] if (n := normalize_op(op))]
            out = {"ops": ops}
            if preview:
                out["preview"] = preview
            return out
    return {"ops": []}


def normalize_evidence(raw: Any) -> dict[str, Any] | None:
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        return {"finding_type": "narrative", "severity": "medium", "summary": text}
    if not isinstance(raw, dict):
        return None
    ev = dict(raw)
    ev.setdefault("finding_type", "narrative")
    ev.setdefault("severity", "medium")
    ev.setdefault("summary", ev.get("finding_id") or ev.get("description") or "Evidence")
    return ev


def normalize_evidence_list(raw: Any) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if isinstance(raw, (str, dict)):
        ev = normalize_evidence(raw)
        return [ev] if ev else []
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        ev = normalize_evidence(item)
        if ev:
            out.append(ev)
    return out


def normalize_shallow_proposal(proposal: dict[str, Any]) -> dict[str, Any]:
    """Normalize one shallow proposal from LLM output before validate/apply."""
    p = dict(proposal)
    if "ops" in p and "patch" not in p:
        p["patch"] = normalize_patch(p.pop("ops"))
    else:
        p["patch"] = normalize_patch(p.get("patch"))
    target = p.get("target")
    if isinstance(target, str):
        p["target"] = {"domain": "global_guidelines", "display_label": target, "field_path": "guidelines_and_rules"}
    elif not isinstance(target, dict):
        p["target"] = {}
    p["evidence"] = normalize_evidence_list(p.get("evidence"))
    return p


def dedupe_target_keys(proposals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    order = {"high": 0, "medium": 1, "low": 2}
    by_key: dict[str, dict[str, Any]] = {}
    for p in proposals:
        key = p.get("target_key")
        if not key:
            continue
        prev = by_key.get(key)
        if not prev:
            by_key[key] = p
            continue
        if order.get(p.get("confidence", "low"), 9) < order.get(prev.get("confidence", "low"), 9):
            by_key[key] = p
    return list(by_key.values())


def validate_shallow_proposal(
    proposal: dict[str, Any],
    blueprint: dict[str, Any],
    dialog_flow: dict[str, Any] | None,
) -> tuple[bool, list[dict[str, Any]]]:
    patch = normalize_patch(proposal.get("patch"))
    if "ops" in proposal and not patch.get("ops"):
        patch = normalize_patch(proposal.get("ops"))
    proposal["patch"] = patch
    target = proposal.get("target") or {}
    if not patch.get("ops"):
        return False, [{"code": "EMPTY_PATCH", "message": "No patch ops"}]
    _, _, errors = apply_patch(blueprint, patch, target, dialog_flow, dry_run=True)
    return len(errors) == 0, errors


def post_process_shallow(
    proposals: list[dict[str, Any]],
    store,
) -> list[dict[str, Any]]:
    bp = load_blueprint(store)
    df = load_dialog_flow(store)
    deduped = dedupe_target_keys(proposals)
    kept: list[dict[str, Any]] = []
    for raw in deduped:
        p = normalize_shallow_proposal(raw)
        if not p.get("id"):
            p["id"] = f"prop-{uuid.uuid4().hex[:12]}"
        p.setdefault("status", "pending")
        ok, errors = validate_shallow_proposal(p, bp, df)
        if ok:
            kept.append(p)
        else:
            from ypervaino.log import get_logger
            get_logger("proposal_validate").warning(
                "dropped proposal %s: %s", p.get("id"), errors
            )
    return kept


def post_process_deep(proposals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
    for raw in proposals:
        p = dict(raw)
        if not p.get("id"):
            p["id"] = f"deep-{uuid.uuid4().hex[:12]}"
        p.setdefault("status", "pending")
        p["evidence"] = normalize_evidence_list(p.get("evidence"))
        title = (p.get("title") or "").strip().lower()
        if title and title in seen_titles:
            continue
        if title:
            seen_titles.add(title)
        out.append(p)
    return out
