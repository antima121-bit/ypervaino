"""Start filter.py subprocesses and stream logs per run."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from web.log_util import (  # noqa: I001 — package import when cwd is analysis_tool
    is_trace_progress_line,
    normalize_log_chunk,
    should_show_in_ui_log,
)

TOOL_DIR = Path(__file__).resolve().parent.parent
RUNS_DIR = TOOL_DIR / "runs"
FILTER_SCRIPT = TOOL_DIR / "filter.py"


def _dir_size_bytes(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for entry in path.rglob("*"):
        if entry.is_file():
            try:
                total += entry.stat().st_size
            except OSError:
                pass
    return total


@dataclass
class RunRecord:
    run_id: str
    run_dir: Path
    study_dir: Path
    config_path: Path
    log_path: Path
    state_path: Path
    status: str = "pending"
    exit_code: int | None = None
    created_at: str = ""
    form: dict[str, Any] = field(default_factory=dict)
    _subscribers: list[Callable[[str, bool], None]] = field(default_factory=list, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    process: subprocess.Popen[bytes] | None = field(default=None, repr=False)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "exit_code": self.exit_code,
            "study_dir": str(self.study_dir),
            "created_at": self.created_at,
            "form": self.form,
        }

    def _persist_state(self) -> None:
        payload = self.to_public_dict()
        self.state_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def _append_log(self, line: str) -> None:
        if not line or not should_show_in_ui_log(line):
            return
        replace_last = False
        with self._lock:
            if is_trace_progress_line(line) and self.log_path.is_file():
                existing = self.log_path.read_text(encoding="utf-8").splitlines()
                if existing and is_trace_progress_line(existing[-1]):
                    existing[-1] = line
                    self.log_path.write_text("\n".join(existing) + "\n", encoding="utf-8")
                    replace_last = True
                else:
                    with self.log_path.open("a", encoding="utf-8") as fh:
                        fh.write(line + "\n")
            else:
                with self.log_path.open("a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
            subs = list(self._subscribers)
        for cb in subs:
            try:
                cb(line, replace_last)
            except Exception:
                pass

    def subscribe(self, callback: Callable[[str, bool], None]) -> None:
        with self._lock:
            self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable[[str, bool], None]) -> None:
        with self._lock:
            if callback in self._subscribers:
                self._subscribers.remove(callback)

    def read_existing_logs(self) -> list[str]:
        if not self.log_path.is_file():
            return []
        return self.log_path.read_text(encoding="utf-8").splitlines()


def _study_name_for_record(rec: RunRecord) -> str:
    name = (rec.form or {}).get("study_name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    if rec.config_path.is_file():
        try:
            import yaml

            raw = yaml.safe_load(rec.config_path.read_text(encoding="utf-8")) or {}
            if isinstance(raw, dict) and raw.get("study_name"):
                return str(raw["study_name"]).strip()
        except Exception:
            pass
    return rec.run_id[:8]


class RunManager:
    def __init__(self) -> None:
        self._runs: dict[str, RunRecord] = {}
        self._lock = threading.Lock()
        RUNS_DIR.mkdir(parents=True, exist_ok=True)
        self._load_existing_runs()

    def _load_existing_runs(self) -> None:
        for run_dir in RUNS_DIR.iterdir():
            if not run_dir.is_dir():
                continue
            state_path = run_dir / "state.json"
            if not state_path.is_file():
                continue
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            run_id = state.get("run_id") or run_dir.name
            study_dir = Path(state.get("study_dir") or (run_dir / "study"))
            rec = RunRecord(
                run_id=run_id,
                run_dir=run_dir,
                study_dir=study_dir,
                config_path=run_dir / "config.yaml",
                log_path=run_dir / "logs.txt",
                state_path=state_path,
                status=state.get("status") or "unknown",
                exit_code=state.get("exit_code"),
                created_at=state.get("created_at") or "",
                form=state.get("form") or {},
            )
            self._runs[run_id] = rec

    def get(self, run_id: str) -> RunRecord | None:
        with self._lock:
            return self._runs.get(run_id)

    def list_runs(self) -> list[dict[str, Any]]:
        with self._lock:
            records = list(self._runs.values())
        rows: list[dict[str, Any]] = []
        for rec in records:
            size_bytes = _dir_size_bytes(rec.run_dir)
            rows.append(
                {
                    "run_id": rec.run_id,
                    "study_name": _study_name_for_record(rec),
                    "status": rec.status,
                    "created_at": rec.created_at,
                    "size_bytes": size_bytes,
                    "size_gb": round(size_bytes / (1024**3), 3),
                    "results_available": rec.status == "success",
                }
            )
        rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
        return rows

    def delete_run(self, run_id: str) -> bool:
        with self._lock:
            rec = self._runs.get(run_id)
        if not rec:
            return False
        if rec.process is not None and rec.process.poll() is None:
            rec.process.terminate()
            try:
                rec.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                rec.process.kill()
        if rec.run_dir.is_dir():
            shutil.rmtree(rec.run_dir, ignore_errors=True)
        with self._lock:
            self._runs.pop(run_id, None)
        return True

    def delete_all_runs(self) -> int:
        with self._lock:
            run_ids = list(self._runs.keys())
        deleted = 0
        for run_id in run_ids:
            if self.delete_run(run_id):
                deleted += 1
        return deleted

    def start_run(
        self,
        *,
        config_yaml_text: str,
        form: dict[str, Any],
        session_limit: int | None = None,
    ) -> RunRecord:
        run_id = uuid.uuid4().hex
        run_dir = RUNS_DIR / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        study_dir = (run_dir / "study").resolve()
        study_dir.mkdir(parents=True, exist_ok=True)

        config_dest = run_dir / "config.yaml"
        config_dest.write_text(config_yaml_text, encoding="utf-8")

        rec = RunRecord(
            run_id=run_id,
            run_dir=run_dir,
            study_dir=study_dir,
            config_path=config_dest,
            log_path=run_dir / "logs.txt",
            state_path=run_dir / "state.json",
            status="running",
            created_at=datetime.now(timezone.utc).isoformat(),
            form=form,
        )
        rec._persist_state()

        cmd = [
            sys.executable,
            str(FILTER_SCRIPT),
            "--config",
            str(config_dest),
            "--study-dir",
            str(study_dir),
        ]
        if session_limit is not None:
            cmd.extend(["--limit", str(session_limit)])
        proc = subprocess.Popen(
            cmd,
            cwd=str(TOOL_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=0,
        )
        rec.process = proc

        with self._lock:
            self._runs[run_id] = rec

        thread = threading.Thread(target=self._pump_output, args=(rec, proc), daemon=True)
        thread.start()
        return rec

    def _pump_output(self, rec: RunRecord, proc: subprocess.Popen[bytes]) -> None:
        assert proc.stdout is not None
        buffer = b""
        try:
            while True:
                chunk = proc.stdout.read(4096)
                if not chunk:
                    break
                buffer += chunk
                while b"\n" in buffer:
                    line_bytes, buffer = buffer.split(b"\n", 1)
                    line = normalize_log_chunk(line_bytes.decode("utf-8", errors="replace"))
                    rec._append_log(line)
                if b"\r" in buffer:
                    segment = buffer.split(b"\r")[-1]
                    if segment.strip():
                        line = normalize_log_chunk(segment.decode("utf-8", errors="replace"))
                        rec._append_log(line)
                    buffer = b""
            if buffer.strip():
                line = normalize_log_chunk(buffer.decode("utf-8", errors="replace"))
                rec._append_log(line)
        finally:
            code = proc.wait()
            rec.exit_code = code
            rec.status = "success" if code == 0 else "failed"
            rec.process = None
            rec._persist_state()
