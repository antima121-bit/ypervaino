from __future__ import annotations

import json
import time
from contextlib import contextmanager
from typing import Any, Iterator

from ypervaino.log import attach_study_log_file, log_kv
from ypervaino.study_store import StudyStore, now_iso


class StudyTimer:
    def __init__(self, store: StudyStore):
        self.store = store
        self._path = store.intermediate_dir / "timing.jsonl"
        self._summary: dict[str, float] = {}
        self.log = attach_study_log_file(store.slug)

    def log_event(
        self,
        phase: str,
        component: str,
        duration_ms: float,
        *,
        session_id: str | None = None,
        cache_hit: bool | None = None,
        counts: dict[str, Any] | None = None,
        llm: dict[str, Any] | None = None,
        error: str | None = None,
        message: str | None = None,
    ) -> None:
        entry = {
            "ts": now_iso(),
            "study_slug": self.store.slug,
            "phase": phase,
            "component": component,
            "session_id": session_id,
            "duration_ms": round(duration_ms, 2),
            "cache_hit": cache_hit,
            "counts": counts,
            "llm": llm,
            "error": error,
            "message": message,
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a") as f:
            f.write(json.dumps(entry, default=str) + "\n")
        key = f"{phase}:{component}"
        self._summary[key] = self._summary.get(key, 0.0) + duration_ms

        if error:
            self.log.error("[%s %s] %s (%.0fms) err=%s", phase, component, message or "failed", duration_ms, error)
        elif message:
            self.log.info("[%s %s] %s (%.0fms)", phase, component, message, duration_ms)
        else:
            self.log.debug("[%s %s] done %.0fms counts=%s", phase, component, duration_ms, counts)

    @contextmanager
    def track(
        self,
        phase: str,
        component: str,
        *,
        start_message: str | None = None,
        done_message: str | None = None,
        **kwargs: Any,
    ) -> Iterator[None]:
        if start_message:
            self.log.info("[%s %s] %s", phase, component, start_message)
        else:
            self.log.info("[%s %s] starting…", phase, component)
        t0 = time.perf_counter()
        err = None
        try:
            yield
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            raise
        finally:
            ms = (time.perf_counter() - t0) * 1000
            self.log_event(
                phase, component, ms,
                error=err,
                message=done_message or ("failed" if err else "complete"),
                **kwargs,
            )

    def write_summary(self) -> None:
        out = {
            "study_slug": self.store.slug,
            "generated_at": now_iso(),
            "component_wall_ms": {k: round(v, 2) for k, v in sorted(self._summary.items())},
        }
        self.store.write_json(self.store.intermediate_dir / "phase_timing_summary.json", out)
        self.log.info("timing summary written → intermediate/phase_timing_summary.json")
        for key, ms in sorted(self._summary.items()):
            self.log.info("  %s: %.1fs", key, ms / 1000)
