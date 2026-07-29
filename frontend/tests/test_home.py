from unittest.mock import patch

from streamlit.testing.v1 import AppTest


def test_page_loads_without_error_when_nothing_uploaded_yet():
    with patch("bootstrap._backend_is_reachable", return_value=True):
        at = AppTest.from_file("Home.py")
        at.run()
    assert not at.exception
