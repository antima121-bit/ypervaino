from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ypervaino.settings import STUDIES_ROOT


def slugify(title: str) -> str:
    s = title.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "study"


def unique_slug(title: str) -> str:
    base = slugify(title)
    slug = base
    n = 2
    while study_dir(slug).exists():
        slug = f"{base}-{n}"
        n += 1
    return slug


def study_dir(slug: str) -> Path:
    return STUDIES_ROOT / slug


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


class StudyStore:
    def __init__(self, slug: str):
        self.slug = slug
        self.root = study_dir(slug)
        self.input_dir = self.root / "input"
        self.cache_dir = self.root / "cache"
        self.intermediate_dir = self.root / "intermediate"
        self.output_dir = self.root / "output"
        self.features_dir = self.cache_dir / "features"
        self.traces_dir = self.cache_dir / "traces"

    def ensure_layout(self) -> None:
        for d in (
            self.input_dir,
            self.cache_dir,
            self.features_dir,
            self.traces_dir,
            self.intermediate_dir,
            self.intermediate_dir / "s_explore",
            self.output_dir,
            self.output_dir / "plots",
            self.output_dir / "tables",
            self.output_dir / "per_conversation",
        ):
            d.mkdir(parents=True, exist_ok=True)

    def meta_path(self) -> Path:
        return self.root / "meta.json"

    def read_meta(self) -> dict[str, Any]:
        return json.loads(self.meta_path().read_text())

    def write_meta(self, meta: dict[str, Any]) -> None:
        meta["updated_at"] = now_iso()
        self.meta_path().write_text(json.dumps(meta, indent=2) + "\n")

    def write_json(self, path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, default=str) + "\n")

    def read_json(self, path: Path) -> Any:
        return json.loads(path.read_text())

    def progress_hints(self) -> dict[str, Any]:
        log_path = self.intermediate_dir / "pipeline.log"
        hints: dict[str, Any] = {
            "cohort_stats_ready": (self.intermediate_dir / "cohort_stats.json").exists(),
            "s_explore_ready": (self.intermediate_dir / "s_explore" / "manifest.json").exists(),
            "analysis_plan_ready": (self.intermediate_dir / "analysis_plan.json").exists(),
            "evaluation_ready": (self.output_dir / "evaluation_result.json").exists(),
            "pipeline_log_ready": log_path.exists(),
        }
        if log_path.exists():
            hints["recent_log_lines"] = self.tail_pipeline_log(8)
        return hints

    def tail_pipeline_log(self, n: int = 100) -> list[str]:
        log_path = self.intermediate_dir / "pipeline.log"
        if not log_path.exists():
            return []
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        return lines[-n:] if n > 0 else lines

    @staticmethod
    def slug_exists(slug: str) -> bool:
        return study_dir(slug).exists()

    @staticmethod
    def title_available(title: str) -> tuple[str, bool]:
        slug = slugify(title)
        if not study_dir(slug).exists():
            return slug, True
        # collision with numeric suffix rule
        n = 2
        while study_dir(f"{slug}-{n}").exists():
            n += 1
        return slug, False
