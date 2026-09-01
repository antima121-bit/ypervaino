from __future__ import annotations

from typing import Any

from ypervaino.data_layer import load_or_fetch_conversation
from ypervaino.features import compute_features
from ypervaino.parallel import run_parallel, worker_count
from ypervaino.study_store import StudyStore


def _scan_notable_and_anomalies(events: list[dict], fv: dict[str, Any]) -> tuple[list[str], list[str]]:
    notable, anomalies = [], []
    tool_errors = sum(1 for e in events if e.get("event_type") == "TOOL_CALL_ERROR")
    if tool_errors:
        notable.append(f"{tool_errors} tool error(s)")
    transfers = sum(1 for e in events if e.get("event_type") == "CALL_TRANSFER_COMPLETED")
    if transfers:
        notable.append(f"{transfers} transfer(s)")
    interruptions = int(fv.get("interruption_count") or 0)
    if interruptions:
        notable.append(f"{interruptions} interruption(s)")
    if fv.get("main_stream_model"):
        notable.append(f"main_stream model={fv.get('main_stream_model')}")
    if fv.get("guardrail_triggered"):
        notable.append("guardrail triggered")

    for e in events:
        et = e.get("event_type")
        ev = e.get("event_value") or {}
        if et == "TOOL_CALL_ERROR":
            anomalies.append("tool_call_error")
        if et == "GUARDRAIL_CHECK" and (ev.get("would_block") or ev.get("flagged_categories")):
            anomalies.append("guardrail_block")
        if et == "SESSION_END" and "timeout" in str(ev.get("status") or ev.get("end_reason") or "").lower():
            anomalies.append("timeout")
        if et == "LLM_INVOCATION_ERROR":
            anomalies.append("llm_error")
        if et == "TOOL_CALL_RESULT" and not ev.get("result") and not ev.get("output"):
            anomalies.append("empty_tool_result")
    return notable, sorted(set(anomalies))


def _transcript_digest(transcript: list[dict]) -> list[dict]:
    if len(transcript) <= 8:
        return transcript
    head = transcript[:3]
    tail = transcript[-2:]
    mid = [t for t in transcript if any(x in (t.get("text") or "").lower() for x in ("error", "transfer", "sorry"))]
    return head + mid[:3] + tail


def build_digest(
    store: StudyStore,
    session_id: str,
    cohort_label: str | None = None,
) -> dict[str, Any]:
    conv = load_or_fetch_conversation(store, session_id)
    fv_path = store.features_dir / f"{session_id}.json"
    if fv_path.exists():
        fv = store.read_json(fv_path)
    else:
        fv = compute_features(conv)
        store.write_json(fv_path, fv)
    events = conv.get("events") or []
    notable, anomalies = _scan_notable_and_anomalies(events, fv)
    transcript = conv.get("transcript") or []
    return {
        "session_id": session_id,
        "cohort_label": cohort_label,
        "opening_intent": fv.get("opening_intent_class"),
        "outcome": fv.get("session_outcome"),
        "turn_count": fv.get("turn_count"),
        "duration_ms": fv.get("session_duration_ms"),
        "transcript_digest": _transcript_digest(transcript),
        "transcript": transcript,
        "notable_events": notable,
        "anomaly_flags": anomalies,
        "primitive_snapshot": {
            k: fv[k] for k in (
                "turn_count", "main_stream_latency_p95", "main_stream_estimated_cost_usd",
                "tool_error_count", "guardrail_triggered", "opening_intent_class",
                "session_outcome", "main_stream_model",
            ) if k in fv
        },
        "bullets": [
            f"turns={fv.get('turn_count')} outcome={fv.get('session_outcome')}",
            f"intent={fv.get('opening_intent_class')} model={fv.get('main_stream_model')}",
            f"latency_p95={fv.get('main_stream_latency_p95')}ms tools={fv.get('tool_invocation_count')}",
        ],
    }


def build_digests_parallel(
    store: StudyStore,
    manifest: dict[str, Any],
    max_workers: int | None = None,
) -> None:
    jobs: list[tuple[str, str | None]] = []
    if manifest.get("pairs"):
        for p in manifest["pairs"]:
            jobs.append((p["before"], "before"))
            jobs.append((p["after"], "after"))
    else:
        for sid in manifest.get("session_ids") or []:
            label = "all"
            if manifest.get("by_cohort"):
                if sid in (manifest["by_cohort"].get("before") or []):
                    label = "before"
                elif sid in (manifest["by_cohort"].get("after") or []):
                    label = "after"
            jobs.append((sid, label))

    def _one(args):
        sid, label = args
        digest = build_digest(store, sid, label)
        store.write_json(store.intermediate_dir / "s_explore" / f"{sid}.digest.json", digest)
        return sid

    run_parallel(jobs, _one, max_workers=max_workers, label="phase2a-digests")


def pick_full_transcripts_for_plan(store: StudyStore, session_ids: list[str]) -> list[dict]:
    digests = []
    for sid in session_ids:
        p = store.intermediate_dir / "s_explore" / f"{sid}.digest.json"
        if p.exists():
            digests.append(store.read_json(p))
    if not digests:
        return []
    shortest = min(digests, key=lambda d: int(d.get("turn_count") or 0))
    longest = max(digests, key=lambda d: int(d.get("turn_count") or 0))
    anomalous = max(digests, key=lambda d: len(d.get("anomaly_flags") or []))
    picked = {shortest["session_id"], longest["session_id"], anomalous["session_id"]}
    return [d for d in digests if d["session_id"] in picked]
