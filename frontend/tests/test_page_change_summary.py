from streamlit.testing.v1 import AppTest


def test_page_prompts_for_a_comparison_when_none_exists():
    at = AppTest.from_file("pages/2_Change_Summary.py")
    at.run()
    assert not at.exception


def test_page_shows_metrics_when_a_comparison_exists():
    at = AppTest.from_file("pages/2_Change_Summary.py")
    at.session_state["comparison"] = {
        "summary": {"total_changes": 3, "high_risk": 2, "medium_risk": 1, "low_risk": 0, "informational": 0}
    }
    at.run()
    assert not at.exception
    metric_values = [m.value for m in at.metric]
    assert "3" in metric_values
    assert "2" in metric_values
