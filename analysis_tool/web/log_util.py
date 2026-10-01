"""Strip ANSI escape codes from subprocess log lines."""

from __future__ import annotations

import re

_ANSI_ESCAPE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


def strip_ansi(text: str) -> str:
    return _ANSI_ESCAPE.sub("", text)


TRACE_PROGRESS_PREFIX = "Traces downloaded:"


def is_trace_progress_line(line: str) -> bool:
    return line.strip().startswith(TRACE_PROGRESS_PREFIX)


def should_show_in_ui_log(line: str) -> bool:
    """Drop Python logging WARNING lines from the web log stream."""
    stripped = line.lstrip()
    return not stripped.startswith("WARNING ")


def normalize_log_chunk(raw: str) -> str:
    """Handle carriage-return progress lines from trace download."""
    text = strip_ansi(raw)
    if "\r" in text and not text.endswith("\n"):
        text = text.split("\r")[-1]
    return text.rstrip("\n")


def collapse_trace_progress_lines(lines: list[str]) -> list[str]:
    """Keep a single in-progress trace download line when replaying logs."""
    out: list[str] = []
    for line in lines:
        if is_trace_progress_line(line):
            if out and is_trace_progress_line(out[-1]):
                out[-1] = line
            else:
                out.append(line)
        else:
            out.append(line)
    return out
