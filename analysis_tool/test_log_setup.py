from log_setup import shorten_study_paths_in_text, study_rel_path


def test_study_rel_path():
    p = (
        "/Users/dwijesh/src/ypervaino/analysis_tool/studies/"
        "uown_study_20260928T181949Z/generated_hypotheses.json"
    )
    assert study_rel_path(p) == "uown_study_20260928T181949Z/generated_hypotheses.json"


def test_shorten_study_paths_in_log_line():
    msg = (
        "Hypothesis generation completed in 12.3s — saved to "
        "/Users/dwijesh/src/ypervaino/analysis_tool/studies/"
        "uown_study_20260928T181949Z/generated_hypotheses.json"
    )
    assert "uown_study_20260928T181949Z/generated_hypotheses.json" in shorten_study_paths_in_text(msg)
    assert "/Users/" not in shorten_study_paths_in_text(msg)
