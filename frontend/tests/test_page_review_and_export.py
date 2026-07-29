from streamlit.testing.v1 import AppTest


def test_page_loads_with_no_comparison():
    at = AppTest.from_file("pages/4_Review_and_Export.py")
    at.run()
    assert not at.exception


def test_page_loads_with_a_comparison():
    at = AppTest.from_file("pages/4_Review_and_Export.py")
    at.session_state["comparison"] = {
        "comparison_id": "cmp-1",
        "changes": [
            {
                "change_id": "1", "section": "Acceptance Criteria", "change_type": "numeric_change",
                "old_text": "95%", "new_text": "98%", "ai_risk_level": "High",
                "reviewer_risk_level": None, "reviewer_comment": None, "accepted": False,
                "reason": "narrowed",
            },
        ],
    }
    at.run()
    assert not at.exception
