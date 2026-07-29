from logic import filter_changes, build_change_update_payload

CHANGES = [
    {"change_id": "1", "section": "Acceptance Criteria", "change_type": "numeric_change", "ai_risk_level": "High", "reviewer_risk_level": None},
    {"change_id": "2", "section": "Storage Conditions", "change_type": "unit_change", "ai_risk_level": "High", "reviewer_risk_level": None},
    {"change_id": "3", "section": "Responsibilities", "change_type": "role_responsibility_change", "ai_risk_level": "Medium", "reviewer_risk_level": "Low"},
]


def test_no_filters_returns_all_changes():
    assert filter_changes(CHANGES, None, None, None) == CHANGES


def test_filter_by_risk_uses_reviewer_override_when_present():
    result = filter_changes(CHANGES, "Low", None, None)
    assert [c["change_id"] for c in result] == ["3"]


def test_filter_by_section():
    result = filter_changes(CHANGES, None, "Storage Conditions", None)
    assert [c["change_id"] for c in result] == ["2"]


def test_filter_by_change_type():
    result = filter_changes(CHANGES, None, None, "numeric_change")
    assert [c["change_id"] for c in result] == ["1"]


def test_combined_filters():
    result = filter_changes(CHANGES, "High", "Storage Conditions", "unit_change")
    assert [c["change_id"] for c in result] == ["2"]


def test_build_change_update_payload_includes_only_changed_fields():
    original = {"reviewer_risk_level": None, "reviewer_comment": None, "accepted": False}
    edited = {"reviewer_risk_level": "Low", "reviewer_comment": None, "accepted": True}

    payload = build_change_update_payload(edited, original)

    assert payload == {"reviewer_risk_level": "Low", "accepted": True}


def test_build_change_update_payload_is_empty_when_nothing_changed():
    row = {"reviewer_risk_level": "Low", "reviewer_comment": "ok", "accepted": True}
    assert build_change_update_payload(row, row) == {}
