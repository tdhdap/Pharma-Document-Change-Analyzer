# backend/tests/test_api.py
from fastapi.testclient import TestClient

from app import config, llm_classifier
from app.main import app
from app.models import LLMClassification

client = TestClient(app)


def setup_isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(config, "UPLOAD_DIR", str(tmp_path / "uploads"))


def fake_classify(unresolved):
    return [
        LLMClassification(
            change_id=item["change_id"], change_type="role_responsibility_change",
            reason="Approval responsibility changed.", confidence=0.9,
        )
        for item in unresolved
    ]


def test_upload_document_returns_id_and_extracted_text(tmp_path, monkeypatch):
    setup_isolated_storage(tmp_path, monkeypatch)
    response = client.post(
        "/documents",
        files={"file": ("old.txt", b"Assay acceptance criterion: 95.0% to 105.0%.", "text/plain")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["filename"] == "old.txt"
    assert body["extracted_text"] == ["Assay acceptance criterion: 95.0% to 105.0%."]
    assert "document_id" in body


def test_upload_rejects_unsupported_file_type(tmp_path, monkeypatch):
    setup_isolated_storage(tmp_path, monkeypatch)
    response = client.post("/documents", files={"file": ("old.xyz", b"data", "application/octet-stream")})
    assert response.status_code == 400


def test_compare_get_patch_and_export_flow(tmp_path, monkeypatch):
    setup_isolated_storage(tmp_path, monkeypatch)
    monkeypatch.setattr(llm_classifier, "classify_changes_batch", fake_classify)

    old_text = (
        b"Assay acceptance criterion: 95.0% to 105.0%.\n\n"
        b"Samples shall be stored at 25\xc2\xb0C \xc2\xb1 2\xc2\xb0C.\n\n"
        b"The Quality Control Manager shall approve the result."
    )
    new_text = (
        b"Assay acceptance criterion: 98.0% to 102.0%.\n\n"
        b"Samples shall be stored at 25\xc2\xb0C \xc2\xb1 2\xc2\xb0C and 60% RH \xc2\xb1 5% RH.\n\n"
        b"The Quality Assurance Manager shall approve the result."
    )

    old_resp = client.post("/documents", files={"file": ("old.txt", old_text, "text/plain")})
    new_resp = client.post("/documents", files={"file": ("new.txt", new_text, "text/plain")})

    compare_resp = client.post("/compare", json={
        "old_document_id": old_resp.json()["document_id"],
        "new_document_id": new_resp.json()["document_id"],
    })
    assert compare_resp.status_code == 200
    comparison = compare_resp.json()
    assert comparison["summary"]["total_changes"] == 3
    comparison_id = comparison["comparison_id"]

    get_resp = client.get(f"/comparisons/{comparison_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["summary"]["total_changes"] == 3

    change_id = comparison["changes"][0]["change_id"]
    patch_resp = client.patch(f"/changes/{change_id}", json={"reviewer_risk_level": "Low", "accepted": True})
    assert patch_resp.status_code == 200
    assert patch_resp.json()["reviewer_risk_level"] == "Low"

    export_resp = client.get(f"/comparisons/{comparison_id}/export", params={"format": "csv"})
    assert export_resp.status_code == 200
    assert "change_id" in export_resp.text


def test_compare_returns_404_for_unknown_document(tmp_path, monkeypatch):
    setup_isolated_storage(tmp_path, monkeypatch)
    response = client.post("/compare", json={"old_document_id": "missing-1", "new_document_id": "missing-2"})
    assert response.status_code == 404
