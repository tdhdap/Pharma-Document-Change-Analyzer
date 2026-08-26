from logic import (
    filter_changes, build_change_update_payload, format_table_cell,
    categorize_change, group_changes_for_display, compute_risk_counts,
    format_group_label, has_high_risk, format_table_coordinates, table_group_key,
)

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


def test_categorize_change_page_header_is_headers():
    change = {"section": "Page Header", "source": "Body"}
    assert categorize_change(change) == "Headers"


def test_categorize_change_qualified_page_header_is_headers():
    change = {"section": "Page Header (Section 2, First Page)", "source": "Body"}
    assert categorize_change(change) == "Headers"


def test_categorize_change_page_footer_is_footers():
    change = {"section": "Page Footer", "source": "Body"}
    assert categorize_change(change) == "Footers"


def test_categorize_change_table_source_is_tables_even_for_regular_section():
    change = {"section": "4.0 Procedure", "source": "Table"}
    assert categorize_change(change) == "Tables"


def test_categorize_change_table_source_is_tables_even_for_text_box():
    change = {"section": "Text Box 1", "source": "Table"}
    assert categorize_change(change) == "Tables"


def test_categorize_change_table_source_is_tables_even_for_page_header():
    # Proves the check order from the plan's Global Constraints: source=="Table"
    # is checked BEFORE the header/footer prefix check, so a table inside a
    # header still lands in "Tables", not "Headers".
    change = {"section": "Page Header", "source": "Table"}
    assert categorize_change(change) == "Tables"


def test_categorize_change_body_sourced_regular_section_is_body():
    change = {"section": "4.0 Procedure", "source": "Body"}
    assert categorize_change(change) == "Body"


def test_categorize_change_text_box_is_body():
    change = {"section": "Text Box 1", "source": "Body"}
    assert categorize_change(change) == "Body"


def test_categorize_change_footnote_is_body():
    change = {"section": "Footnote 1", "source": "Body"}
    assert categorize_change(change) == "Body"


def test_categorize_change_defaults_source_to_body_when_absent():
    # Change.source always exists on real API responses, but categorize_change
    # should not crash on a dict missing it.
    change = {"section": "4.0 Procedure"}
    assert categorize_change(change) == "Body"


def test_section_added_with_table_content_is_not_routed_to_tables():
    # These rows carry source="Table" when the section contained cells, but they
    # have no table coordinates - routing them to Tables makes table_group_key
    # dereference None and the page raises.
    change = {
        "section": "4.0 Procedure",
        "source": "Table",
        "change_type": "section_added",
        "old_table_position": None,
        "new_table_position": None,
    }
    assert categorize_change(change) == "Body"


def test_section_deleted_with_table_content_is_not_routed_to_tables():
    change = {
        "section": "4.0 Procedure",
        "source": "Table",
        "change_type": "section_deleted",
        "old_table_position": None,
        "new_table_position": None,
    }
    assert categorize_change(change) == "Body"


def test_whole_section_row_in_a_header_still_routes_to_headers():
    change = {
        "section": "Page Header",
        "source": "Table",
        "change_type": "section_added",
        "old_table_position": None,
        "new_table_position": None,
    }
    assert categorize_change(change) == "Headers"


def test_real_table_cell_change_still_routes_to_tables():
    # Guard that the fix did not over-broaden: genuine cell-level changes must
    # still reach the Tables group.
    change = {
        "section": "4.0 Procedure",
        "source": "Table",
        "change_type": "numeric_change",
        "old_table_position": {"table_id": 0, "row": 1, "col": 2},
        "new_table_position": {"table_id": 0, "row": 1, "col": 2},
    }
    assert categorize_change(change) == "Tables"


def test_group_changes_for_display_all_four_keys_always_present():
    result = group_changes_for_display([])
    assert set(result.keys()) == {"Headers", "Footers", "Body", "Tables"}
    assert result["Headers"] == []
    assert result["Footers"] == []
    assert result["Body"] == {}
    assert result["Tables"] == {}


def test_group_changes_for_display_sorts_into_correct_categories():
    changes = [
        {"change_id": "h1", "section": "Page Header", "source": "Body"},
        {"change_id": "f1", "section": "Page Footer", "source": "Body"},
        {"change_id": "b1", "section": "2.0 Scope", "source": "Body"},
        {"change_id": "t1", "section": "4.0 Procedure", "source": "Table"},
    ]
    result = group_changes_for_display(changes)
    assert [c["change_id"] for c in result["Headers"]] == ["h1"]
    assert [c["change_id"] for c in result["Footers"]] == ["f1"]
    assert [c["change_id"] for c in result["Body"]["2.0 Scope"]] == ["b1"]
    assert [c["change_id"] for c in result["Tables"]["4.0 Procedure"]] == ["t1"]


def test_group_changes_for_display_sections_in_first_seen_order():
    changes = [
        {"change_id": "1", "section": "8.0 Training Requirements", "source": "Body"},
        {"change_id": "2", "section": "2.0 Scope", "source": "Body"},
        {"change_id": "3", "section": "8.0 Training Requirements", "source": "Body"},
    ]
    result = group_changes_for_display(changes)
    assert list(result["Body"].keys()) == ["8.0 Training Requirements", "2.0 Scope"]
    assert [c["change_id"] for c in result["Body"]["8.0 Training Requirements"]] == ["1", "3"]


def test_group_changes_for_display_multiple_table_sections_kept_separate():
    changes = [
        {"change_id": "1", "section": "4.0 Procedure", "source": "Table"},
        {"change_id": "2", "section": "5.0 In-Process Controls", "source": "Table"},
    ]
    result = group_changes_for_display(changes)
    assert list(result["Tables"].keys()) == ["4.0 Procedure", "5.0 In-Process Controls"]


def test_compute_risk_counts_empty_for_no_changes():
    assert compute_risk_counts([]) == {}


def test_compute_risk_counts_counts_and_orders_by_severity():
    changes = [
        {"ai_risk_level": "Low", "reviewer_risk_level": None},
        {"ai_risk_level": "High", "reviewer_risk_level": None},
        {"ai_risk_level": "High", "reviewer_risk_level": None},
        {"ai_risk_level": "Medium", "reviewer_risk_level": None},
    ]
    result = compute_risk_counts(changes)
    assert list(result.items()) == [("High", 2), ("Medium", 1), ("Low", 1)]


def test_compute_risk_counts_uses_reviewer_override():
    changes = [{"ai_risk_level": "High", "reviewer_risk_level": "Low"}]
    assert compute_risk_counts(changes) == {"Low": 1}


def test_format_group_label_zero_changes():
    assert format_group_label("Footers", []) == "Footers — 0 changes"


def test_format_group_label_single_tier_singular():
    changes = [{"ai_risk_level": "Informational", "reviewer_risk_level": None}]
    result = format_group_label("6.0 Quality Control Release", changes)
    assert result == "⚪ 6.0 Quality Control Release — 1 change (1 Informational)"


def test_format_group_label_mixed_tiers_uses_highest_severity_emoji():
    changes = [
        {"ai_risk_level": "High", "reviewer_risk_level": None},
        {"ai_risk_level": "High", "reviewer_risk_level": None},
        {"ai_risk_level": "High", "reviewer_risk_level": None},
        {"ai_risk_level": "Medium", "reviewer_risk_level": None},
        {"ai_risk_level": "Medium", "reviewer_risk_level": None},
    ]
    result = format_group_label("4.0 Procedure", changes)
    assert result == "\U0001f534 4.0 Procedure — 5 changes (3 High, 2 Medium)"


def test_has_high_risk_true_when_present():
    changes = [{"ai_risk_level": "Low", "reviewer_risk_level": None}, {"ai_risk_level": "High", "reviewer_risk_level": None}]
    assert has_high_risk(changes) is True


def test_has_high_risk_false_when_absent():
    changes = [{"ai_risk_level": "Low", "reviewer_risk_level": None}, {"ai_risk_level": "Medium", "reviewer_risk_level": None}]
    assert has_high_risk(changes) is False


def test_has_high_risk_false_for_empty_list():
    assert has_high_risk([]) is False


def test_has_high_risk_respects_reviewer_override_downgrade():
    changes = [{"ai_risk_level": "High", "reviewer_risk_level": "Low"}]
    assert has_high_risk(changes) is False


def test_format_table_coordinates_both_none():
    assert format_table_coordinates(None, None) == ("", "")


def test_format_table_coordinates_identical_positions_are_1_indexed():
    position = {"table_id": 0, "row": 1, "col": 2}
    assert format_table_coordinates(position, position) == ("2", "3")


def test_format_table_coordinates_only_new_present_is_1_indexed():
    new_position = {"table_id": 0, "row": 3, "col": 0}
    assert format_table_coordinates(None, new_position) == ("4", "1")


def test_format_table_coordinates_only_old_present_is_1_indexed():
    old_position = {"table_id": 0, "row": 2, "col": 1}
    assert format_table_coordinates(old_position, None) == ("3", "2")


def test_format_table_coordinates_row_moved_col_same_is_1_indexed():
    old_position = {"table_id": 0, "row": 1, "col": 0}
    new_position = {"table_id": 0, "row": 3, "col": 0}
    assert format_table_coordinates(old_position, new_position) == ("2 → 4", "1")


def test_format_table_coordinates_col_moved_row_same_is_1_indexed():
    old_position = {"table_id": 0, "row": 1, "col": 0}
    new_position = {"table_id": 1, "row": 1, "col": 2}
    assert format_table_coordinates(old_position, new_position) == ("2", "1 → 3")


def test_table_group_key_uses_new_position_table_id_when_both_present():
    change = {
        "old_table_position": {"table_id": 0, "row": 1, "col": 0},
        "new_table_position": {"table_id": 0, "row": 1, "col": 0},
    }
    assert table_group_key(change) == 0


def test_table_group_key_uses_new_position_table_id_when_it_differs_from_old():
    change = {
        "old_table_position": {"table_id": 0, "row": 1, "col": 0},
        "new_table_position": {"table_id": 1, "row": 1, "col": 2},
    }
    assert table_group_key(change) == 1


def test_table_group_key_falls_back_to_old_position_when_new_is_absent():
    change = {
        "old_table_position": {"table_id": 2, "row": 0, "col": 0},
        "new_table_position": None,
    }
    assert table_group_key(change) == 2


def test_table_group_key_uses_new_position_when_old_is_absent():
    change = {
        "old_table_position": None,
        "new_table_position": {"table_id": 3, "row": 0, "col": 0},
    }
    assert table_group_key(change) == 3


def test_table_group_key_survives_a_missing_position():
    # A Table row with no coordinates at all used to take the whole page down
    # with TypeError: 'NoneType' object is not subscriptable.
    change = {
        "section": "Table 1", "source": "Table", "change_type": "table_row_added",
        "old_table_position": None, "new_table_position": None,
    }
    assert table_group_key(change) == -1
