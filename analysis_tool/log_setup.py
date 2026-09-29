"""Colored stderr logging when the terminal supports it."""

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path

_STUDIES_DIR_MARKER = "/studies/"
_STUDIES_PATH_IN_TEXT_RE = re.compile(r"[^\s\"']+/studies/(\S+)")


def study_rel_path(path: Path | str) -> str:
    """Log-friendly path: ``uown_study_…/file.json`` instead of a full absolute path."""
    s = str(path).replace("\\", "/")
    idx = s.find(_STUDIES_DIR_MARKER)
    if idx >= 0:
        return s[idx + len(_STUDIES_DIR_MARKER) :]
    return s


def shorten_study_paths_in_text(text: str) -> str:
    """Replace any absolute …/studies/… path segments in a log message."""

    def _repl(match: re.Match[str]) -> str:
        tail = match.group(1)
        while tail and tail[-1] in ".,;:)":
            tail = tail[:-1]
        return tail

    normalized = text.replace("\\", "/")
    return _STUDIES_PATH_IN_TEXT_RE.sub(_repl, normalized)

_RESET = "\033[0m"
_LEVEL_COLORS = {
    logging.DEBUG: "\033[36m",
    logging.INFO: "\033[32m",
    logging.WARNING: "\033[33m",
    logging.ERROR: "\033[31m",
    logging.CRITICAL: "\033[35m",
}


class _ColorFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        message = shorten_study_paths_in_text(super().format(record))
        if not sys.stderr.isatty():
            return message
        color = _LEVEL_COLORS.get(record.levelno, "")
        if not color:
            return message
        return f"{color}{message}{_RESET}"


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(
        _ColorFormatter("%(levelname)s %(message)s"),
    )
    logging.basicConfig(level=level, handlers=[handler], force=True)
