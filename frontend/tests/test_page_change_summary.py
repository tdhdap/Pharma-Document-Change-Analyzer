from unittest.mock import patch

from streamlit.testing.v1 import AppTest


def test_page_prompts_for_a_comparison_when_none_exists():
    with patch("bootstrap._backend_is_reachable", return_value=True):
        at = AppTest.from_file("pages/1_Change_Summary.py")
        at.run()
    assert not at.exception


def test_page_shows_metrics_when_a_comparison_exists():
    with patch("bootstrap._backend_is_reachable", return_value=True):
        at = AppTest.from_file("pages/1_Change_Summary.py")
        at.session_state["comparison"] = {
            "summary": {"total_changes": 3, "high_risk": 2, "medium_risk": 1, "low_risk": 0, "informational": 0}
        }
        at.run()
    assert not at.exception
    metric_values = [m.value for m in at.metric]
    assert "3" in metric_values
    assert "2" in metric_values


def test_page_shows_structural_metrics():
    with patch("bootstrap._backend_is_reachable", return_value=True):
        at = AppTest.from_file("pages/1_Change_Summary.py")
        at.session_state["comparison"] = {
            "summary": {
                "total_changes": 6, "high_risk": 3, "medium_risk": 1,
                "low_risk": 0, "informational": 2,
                "sections_added": 2, "sections_deleted": 1, "sections_renamed": 1,
                "sections_renumbered": 1, "sections_cascaded": 0, "sections_moved": 1,
            }
        }
        at.run()

    assert not at.exception
    labels = [m.label for m in at.metric]
    assert "Sections Moved" in labels
    assert "Sections Cascaded" in labels


def test_page_survives_a_summary_without_structural_counts():
    # Indexing these keys took the whole page down with a KeyError against a
    # summary produced before the fields existed - the same failure mode a prior
    # review found in the Detailed Changes table renderer.
    with patch("bootstrap._backend_is_reachable", return_value=True):
        at = AppTest.from_file("pages/1_Change_Summary.py")
        at.session_state["comparison"] = {
            "summary": {"total_changes": 3, "high_risk": 2, "medium_risk": 1,
                        "low_risk": 0, "informational": 0}
        }
        at.run()

    assert not at.exception
