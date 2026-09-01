from __future__ import annotations

import threading
import traceback
from typing import Any

from ypervaino.pipeline import (
    phase0_cohort,
    phase1_sample,
    phase2a_digests,
    phase2b_plan,
    phase3_evaluate,
)
from ypervaino.study_store import StudyStore, now_iso, unique_slug
from ypervaino.timing import StudyTimer
from ypervaino.log import get_logger

_log = get_logger("runner")


class StudyRunner:
    _locks: dict[str, threading.Lock] = {}

    @classmethod
    def _lock_for(cls, slug: str) -> threading.Lock:
        if slug not in cls._locks:
            cls._locks[slug] = threading.Lock()
        return cls._locks[slug]

    def create_study(self, req: dict[str, Any]) -> dict[str, Any]:
        slug = unique_slug(req["study_title"])
        store = StudyStore(slug)
        store.ensure_layout()
        meta = {
            "title": req["study_title"],
            "slug": slug,
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "status": "created",
            "error": None,
        }
        store.write_meta(meta)
        store.write_json(store.input_dir / "create_study.json", req)

        if req.get("study_type") == "comparative":
            n = int(req.get("n_explore") or 100)
            if n % 2 != 0:
                raise ValueError("n_explore must be even for comparative studies")

        t = threading.Thread(target=self._run_phases_0_2, args=(slug,), daemon=True)
        t.start()
        _log.info("study created slug=%s title=%r → background phases 0-2", slug, req["study_title"])
        return meta

    def _run_phases_0_2(self, slug: str) -> None:
        store = StudyStore(slug)
        timer = StudyTimer(store)
        timer.log.info("=== Phases 0–2 started ===")
        with self._lock_for(slug):
            try:
                meta = store.read_meta()
                meta["status"] = "running"
                meta["error"] = None
                store.write_meta(meta)
                req = store.read_json(store.input_dir / "create_study.json")
                timer.log.info(
                    "study_type=%s tenant=%s assistant=%s n_explore=%s n_eval=%s filters=%d",
                    req.get("study_type"), req.get("tenant"), req.get("assistant_origin_id"),
                    req.get("n_explore"), req.get("n_eval"), len(req.get("cohort_filters") or []),
                )
                p0 = phase0_cohort(store, req, timer)
                manifest = phase1_sample(store, p0["stats"], req, p0["features"], timer)
                phase2a_digests(store, manifest, timer)
                phase2b_plan(store, req, manifest, p0["stats"], timer)
                timer.write_summary()
                meta = store.read_meta()
                meta["status"] = "explored"
                meta["error"] = None
                store.write_meta(meta)
                timer.log.info("=== Phases 0–2 complete → status=explored ===")
            except Exception as e:
                timer.log.exception("Phases 0–2 failed")
                meta = store.read_meta()
                meta["status"] = "failed"
                meta["error"] = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
                store.write_meta(meta)
                timer.write_summary()

    def execute(self, slug: str) -> None:
        store = StudyStore(slug)
        meta = store.read_meta()
        if meta["status"] != "explored":
            raise ValueError(f"Cannot execute in status {meta['status']}")
        plan = store.read_json(store.intermediate_dir / "analysis_plan.json")
        plan["user_approved"] = True
        store.write_json(store.intermediate_dir / "analysis_plan.json", plan)
        meta["status"] = "running"
        meta["error"] = None
        store.write_meta(meta)
        t = threading.Thread(target=self._run_phase_3, args=(slug,), daemon=True)
        t.start()
        _log.info("phase 3 queued slug=%s", slug)

    def _run_phase_3(self, slug: str) -> None:
        store = StudyStore(slug)
        timer = StudyTimer(store)
        timer.log.info("=== Phase 3 started ===")
        with self._lock_for(slug):
            try:
                req = store.read_json(store.input_dir / "create_study.json")
                stats = store.read_json(store.intermediate_dir / "cohort_stats.json")
                plan = store.read_json(store.intermediate_dir / "analysis_plan.json")
                n_sessions = sum(len(v) for v in stats.get("session_ids", {}).values())
                timer.log.info("evaluating %d sessions, %d aspects, %d hypotheses",
                               n_sessions,
                               len((plan.get("quantitative") or {}).get("aspects") or []),
                               len((plan.get("qualitative") or {}).get("hypotheses") or []))
                phase3_evaluate(store, req, stats, plan, timer)
                timer.write_summary()
                meta = store.read_meta()
                meta["status"] = "complete"
                meta["error"] = None
                store.write_meta(meta)
                timer.log.info("=== Phase 3 complete → status=complete ===")
            except Exception as e:
                timer.log.exception("Phase 3 failed")
                meta = store.read_meta()
                meta["status"] = "failed"
                meta["error"] = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
                store.write_meta(meta)
                timer.write_summary()
