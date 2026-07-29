import json

from app import llm_classifier
from app.llm_classifier import classify_changes_batch


def test_empty_input_returns_empty_list_without_calling_gemini(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("_call_gemini should not be called for empty input")

    monkeypatch.setattr(llm_classifier, "_call_gemini", fail_if_called)
    assert classify_changes_batch([]) == []


def test_parses_successful_gemini_response(monkeypatch):
    unresolved = [
        {"change_id": "c1", "old_text": "The QC Manager shall approve.", "new_text": "The QA Manager shall approve."},
    ]

    def fake_call_gemini(items, model_name):
        return json.dumps([
            {
                "change_id": "c1",
                "change_type": "role_responsibility_change",
                "reason": "Approval responsibility changed from QC Manager to QA Manager.",
                "confidence": 0.9,
            }
        ])

    monkeypatch.setattr(llm_classifier, "_call_gemini", fake_call_gemini)

    results = classify_changes_batch(unresolved)

    assert len(results) == 1
    assert results[0].change_id == "c1"
    assert results[0].change_type == "role_responsibility_change"
    assert results[0].confidence == 0.9


def test_gemini_failure_falls_back_to_unclassified(monkeypatch):
    unresolved = [
        {"change_id": "c1", "old_text": "a", "new_text": "b"},
        {"change_id": "c2", "old_text": "c", "new_text": "d"},
    ]

    def raise_error(items, model_name):
        raise RuntimeError("network error")

    monkeypatch.setattr(llm_classifier, "_call_gemini", raise_error)

    results = classify_changes_batch(unresolved)

    assert len(results) == 2
    assert all(r.change_type == "unclassified" for r in results)
    assert all(r.confidence == 0.0 for r in results)
    assert {r.change_id for r in results} == {"c1", "c2"}
