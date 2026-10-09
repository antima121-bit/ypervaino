"""Trace fetch falls back from /trace to /mongo-trace."""

from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from filter import _fetch_one_trace


def test_mongo_fallback_after_elastic_404(tmp_path: Path):
    log_dir = tmp_path / "log_traces"
    log_dir.mkdir()
    session_id = "64ba4379-1e25-435e-8688-ce2834dd0b08"
    mongo_payload = {
        "session_id": "6a83a0dc14220bfb70dfe593",
        "resolved_from": "voice",
        "events": [{"event_type": "USER_QUERY", "content": "hi", "event_value": {}}],
    }

    class Resp:
        def __init__(self, data: bytes):
            self._data = data
            self.status = 200

        def read(self):
            return self._data

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen2(url, timeout=0):
        if "/trace?" in url and "/mongo-trace" not in url:
            raise HTTPError(url, 404, "Not Found", hdrs=None, fp=BytesIO(b"{}"))
        if "/mongo-trace?" in url:
            return Resp(json.dumps(mongo_payload).encode())
        raise AssertionError(url)

    with patch("filter.urlopen", side_effect=fake_urlopen2):
        result = _fetch_one_trace(
            session_id,
            trace_base_url="http://botprobe.test",
            trace_env="prod",
            log_traces_dir=log_dir,
            retry_count=1,
            request_timeout_s=5,
        )

    assert result["ok"] is True
    assert result["trace_source"] == "mongo"
    saved = json.loads((log_dir / f"{session_id}.json").read_text())
    assert saved["trace_source"] == "mongo"
    assert len(saved["events"]) == 1
