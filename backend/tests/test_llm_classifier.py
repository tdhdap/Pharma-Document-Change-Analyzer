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


def test_change_type_outside_semantic_types_is_forced_to_unclassified(monkeypatch):
    unresolved = [{"change_id": "c1", "old_text": "a", "new_text": "b"}]

    def fake_call_gemini(items, model_name):
        return json.dumps([
            {"change_id": "c1", "change_type": "numeric_change", "reason": "restated a regex fact", "confidence": 0.8},
        ])

    monkeypatch.setattr(llm_classifier, "_call_gemini", fake_call_gemini)

    results = classify_changes_batch(unresolved)

    assert len(results) == 1
    assert results[0].change_type == "unclassified"


def test_prompt_includes_already_detected_hint_when_present():
    unresolved = [
        {"change_id": "c1", "old_text": "a", "new_text": "b", "already_detected": ["numeric_change"]},
    ]
    prompt = llm_classifier._build_prompt(unresolved)
    assert "already_detected" in prompt
    assert "numeric_change" in prompt


def test_prompt_omits_already_detected_key_when_empty_or_absent():
    unresolved_empty = [{"change_id": "c1", "old_text": "a", "new_text": "b", "already_detected": []}]
    unresolved_absent = [{"change_id": "c1", "old_text": "a", "new_text": "b"}]
    prompt_empty = llm_classifier._build_prompt(unresolved_empty)
    prompt_absent = llm_classifier._build_prompt(unresolved_absent)
    assert '"already_detected"' not in prompt_empty
    assert '"already_detected"' not in prompt_absent
