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
        return meta

    def _run_phases_0_2(self, slug: str) -> None:
        store = StudyStore(slug)
        with self._lock_for(slug):
            try:
                meta = store.read_meta()
                meta["status"] = "running"
                meta["error"] = None
                store.write_meta(meta)
                req = store.read_json(store.input_dir / "create_study.json")
                p0 = phase0_cohort(store, req)
                manifest = phase1_sample(p0["stats"], int(req.get("n_explore") or 100), req["study_type"])
                store.write_json(store.intermediate_dir / "s_explore" / "manifest.json", manifest)
                phase2a_digests(store, manifest["session_ids"])
                phase2b_plan(store, req, manifest, p0["stats"])
                meta = store.read_meta()
                meta["status"] = "explored"
                meta["error"] = None
                store.write_meta(meta)
            except Exception as e:
                meta = store.read_meta()
                meta["status"] = "failed"
                meta["error"] = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
                store.write_meta(meta)

    def execute(self, slug: str) -> None:
        store = StudyStore(slug)
        meta = store.read_meta()
        if meta["status"] != "explored":
            raise ValueError(f"Cannot execute in status {meta['status']}")
        plan = store.read_json(store.intermediate_dir / "analysis_plan.json")
        if plan.get("user_approved"):
            raise ValueError("Plan already executed")
        plan["user_approved"] = True
        store.write_json(store.intermediate_dir / "analysis_plan.json", plan)
        meta["status"] = "running"
        meta["error"] = None
        store.write_meta(meta)
        t = threading.Thread(target=self._run_phase_3, args=(slug,), daemon=True)
        t.start()

    def _run_phase_3(self, slug: str) -> None:
        store = StudyStore(slug)
        with self._lock_for(slug):
            try:
                req = store.read_json(store.input_dir / "create_study.json")
                stats = store.read_json(store.intermediate_dir / "cohort_stats.json")
                plan = store.read_json(store.intermediate_dir / "analysis_plan.json")
                phase3_evaluate(store, req, stats, plan)
                meta = store.read_meta()
                meta["status"] = "complete"
                meta["error"] = None
                store.write_meta(meta)
            except Exception as e:
                meta = store.read_meta()
                meta["status"] = "failed"
                meta["error"] = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
                store.write_meta(meta)
