from unittest.mock import patch, Mock

import api_client


def test_upload_document_posts_file_and_returns_json():
    fake_response = Mock(status_code=200)
    fake_response.json.return_value = {"document_id": "doc-1", "filename": "old.txt", "extracted_text": ["a"]}
    fake_response.raise_for_status.return_value = None

    with patch("api_client.requests.post", return_value=fake_response) as mock_post:
        result = api_client.upload_document("old.txt", b"content")

    assert result["document_id"] == "doc-1"
    args, kwargs = mock_post.call_args
    assert args[0] == f"{api_client.API_BASE_URL}/documents"
    assert kwargs["files"]["file"][0] == "old.txt"


def test_compare_documents_posts_ids_as_json():
    fake_response = Mock(status_code=200)
    fake_response.json.return_value = {"comparison_id": "cmp-1", "summary": {"total_changes": 3}}
    fake_response.raise_for_status.return_value = None

    with patch("api_client.requests.post", return_value=fake_response) as mock_post:
        result = api_client.compare_documents("old-id", "new-id")

    assert result["comparison_id"] == "cmp-1"
    _, kwargs = mock_post.call_args
    assert kwargs["json"] == {"old_document_id": "old-id", "new_document_id": "new-id"}


def test_get_comparison_calls_expected_url():
    fake_response = Mock(status_code=200)
    fake_response.json.return_value = {"comparison_id": "cmp-1"}
    fake_response.raise_for_status.return_value = None

    with patch("api_client.requests.get", return_value=fake_response) as mock_get:
        api_client.get_comparison("cmp-1")

    mock_get.assert_called_once_with(f"{api_client.API_BASE_URL}/comparisons/cmp-1")


def test_update_change_sends_patch_with_given_fields():
    fake_response = Mock(status_code=200)
    fake_response.json.return_value = {"reviewer_risk_level": "Low"}
    fake_response.raise_for_status.return_value = None

    with patch("api_client.requests.patch", return_value=fake_response) as mock_patch:
        api_client.update_change("ch-1", reviewer_risk_level="Low", accepted=True)

    args, kwargs = mock_patch.call_args
    assert args[0] == f"{api_client.API_BASE_URL}/changes/ch-1"
    assert kwargs["json"] == {"reviewer_risk_level": "Low", "accepted": True}


def test_export_comparison_returns_raw_bytes():
    fake_response = Mock(status_code=200, content=b"csv,data")
    fake_response.raise_for_status.return_value = None

    with patch("api_client.requests.get", return_value=fake_response) as mock_get:
        result = api_client.export_comparison("cmp-1", "csv")

    assert result == b"csv,data"
    _, kwargs = mock_get.call_args
    assert kwargs["params"] == {"format": "csv"}
