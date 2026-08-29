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
    # Distinct values per metric, and each asserted against its own label. Equal
    # values let a metric render another metric's count under the right label and
    # still pass. The "Sections" prefix is spec-mandated - the report elsewhere
    # holds moved paragraphs, moved table content and table rows, so a bare
    # "Moved" would be ambiguous - so the labels are pinned exactly.
    with patch("bootstrap._backend_is_reachable", return_value=True):
        at = AppTest.from_file("pages/1_Change_Summary.py")
        at.session_state["comparison"] = {
            "summary": {
                "total_changes": 21, "high_risk": 3, "medium_risk": 1,
                "low_risk": 0, "informational": 2,
                "sections_added": 1, "sections_deleted": 2, "sections_renamed": 3,
                "sections_renumbered": 4, "sections_cascaded": 5, "sections_moved": 6,
            }
        }
        at.run()

    assert not at.exception
    by_label = {m.label: m.value for m in at.metric}
    assert by_label["Sections Added"] == "1"
    assert by_label["Sections Deleted"] == "2"
    assert by_label["Sections Renamed"] == "3"
    assert by_label["Sections Renumbered"] == "4"
    assert by_label["Sections Cascaded"] == "5"
    assert by_label["Sections Moved"] == "6"


def test_page_explains_what_cascaded_means():
    # "Cascaded" is the one label a reviewer cannot infer, so the spec makes its
    # tooltip non-negotiable. Nothing else pins it.
    with patch("bootstrap._backend_is_reachable", return_value=True):
        at = AppTest.from_file("pages/1_Change_Summary.py")
        at.session_state["comparison"] = {
            "summary": {
                "total_changes": 0, "high_risk": 0, "medium_risk": 0,
                "low_risk": 0, "informational": 0,
                "sections_added": 0, "sections_deleted": 0, "sections_renamed": 0,
                "sections_renumbered": 0, "sections_cascaded": 0, "sections_moved": 0,
            }
        }
        at.run()

    assert not at.exception
    cascaded = next(m for m in at.metric if m.label == "Sections Cascaded")
    assert cascaded.help == (
        "Number shifted only because a section above was added or removed; "
        "wording unchanged."
    )


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
