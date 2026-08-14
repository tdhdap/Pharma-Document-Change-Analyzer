from logic import filter_changes, build_change_update_payload, format_table_cell

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


def test_format_table_cell_empty_when_both_positions_are_none():
    assert format_table_cell(None, None) == ""


def test_format_table_cell_shows_position_when_identical():
    position = {"table_id": 0, "row": 1, "col": 1}
    assert format_table_cell(position, position) == "Table 0, Row 1, Col 1"


def test_format_table_cell_shows_arrow_when_positions_differ():
    old_position = {"table_id": 0, "row": 1, "col": 0}
    new_position = {"table_id": 1, "row": 0, "col": 0}
    result = format_table_cell(old_position, new_position)
    assert result == "Table 0, Row 1, Col 0 -> Table 1, Row 0, Col 0"


def test_format_table_cell_shows_only_populated_side():
    new_position = {"table_id": 1, "row": 3, "col": 0}
    assert format_table_cell(None, new_position) == "Table 1, Row 3, Col 0"
