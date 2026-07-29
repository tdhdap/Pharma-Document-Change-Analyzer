from streamlit.testing.v1 import AppTest


def test_page_loads_without_error_when_nothing_uploaded_yet():
    at = AppTest.from_file("pages/1_Upload_and_Compare.py")
    at.run()
    assert not at.exception
