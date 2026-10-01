from web.log_util import (
    collapse_trace_progress_lines,
    is_trace_progress_line,
    should_show_in_ui_log,
)


def test_should_show_in_ui_log():
    assert should_show_in_ui_log("INFO ok")
    assert not should_show_in_ui_log("WARNING deep union skip")


def test_is_trace_progress_line():
    assert is_trace_progress_line("Traces downloaded: 1/10 (1 ok)")
    assert not is_trace_progress_line("INFO something")


def test_collapse_trace_progress_lines():
    lines = [
        "INFO start",
        "Traces downloaded: 1/10 (0 ok)",
        "Traces downloaded: 2/10 (1 ok)",
        "Traces downloaded: 10/10 (10 ok)",
        "INFO done",
    ]
    assert collapse_trace_progress_lines(lines) == [
        "INFO start",
        "Traces downloaded: 10/10 (10 ok)",
        "INFO done",
    ]
