from unittest.mock import patch

from streamlit.testing.v1 import AppTest


def test_page_loads_with_no_comparison():
    with patch("bootstrap._backend_is_reachable", return_value=True):
        at = AppTest.from_file("pages/2_Detailed_Changes.py")
        at.run()
    assert not at.exception


def test_page_loads_with_a_comparison():
    with patch("bootstrap._backend_is_reachable", return_value=True):
        at = AppTest.from_file("pages/2_Detailed_Changes.py")
        at.session_state["comparison"] = {
            "changes": [
                {
                    "change_id": "1", "section": "Acceptance Criteria", "change_type": "numeric_change",
                    "old_text": "95%", "new_text": "98%", "ai_risk_level": "High",
                    "reviewer_risk_level": None, "reason": "narrowed",
                },
            ]
        }
        at.run()
    assert not at.exception
