from app.models import Paragraph, TableCoordinate
from app.table_diff import (
    build_grids, match_tables, _match_lines, diff_rows, diff_columns, diff_merges,
    detect_table_structure_changes,
)


def cell(table_id, row, col, text, row_span=1, col_span=1):
    return Paragraph(
        text=text,
        from_table=True,
        table_position=TableCoordinate(
            table_id=table_id, row=row, col=col, row_span=row_span, col_span=col_span
        ),
    )


def test_build_grids_groups_cells_by_table():
    paragraphs = [
        Paragraph(text="not a table cell"),
        cell(0, 0, 0, "A"), cell(0, 0, 1, "B"),
        cell(1, 0, 0, "X"),
    ]

    grids = build_grids(paragraphs)

    assert set(grids) == {0, 1}
    assert grids[0].rows == [0]
    assert grids[0].cols == [0, 1]
    assert grids[0].text_at(0, 0) == "A"
    assert grids[1].text_at(0, 0) == "X"


def test_build_grids_joins_multiple_paragraphs_in_one_cell():
    paragraphs = [cell(0, 0, 0, "first"), cell(0, 0, 0, "second")]

    grids = build_grids(paragraphs)

    assert grids[0].text_at(0, 0) == "first second"


def test_build_grids_records_spans_and_leaves_merged_positions_absent():
    # A horizontally merged cell occupies only its anchor, so (0, 1) has no entry.
    paragraphs = [cell(0, 0, 0, "merged", col_span=2), cell(0, 1, 0, "below")]

    grids = build_grids(paragraphs)

    assert grids[0].span_at(0, 0) == (1, 2)
    assert grids[0].text_at(0, 1) == ""


def test_row_and_column_text_join_cells_in_order():
    paragraphs = [
        cell(0, 0, 0, "Param"), cell(0, 0, 1, "Spec"),
        cell(0, 1, 0, "Assay"), cell(0, 1, 1, "95%"),
    ]

    grid = build_grids(paragraphs)[0]

    assert grid.row_text(1) == "Assay | 95%"
    assert grid.col_text(0) == "Param | Assay"


def test_match_tables_pairs_by_content_not_by_table_id():
    # The same table appears as table_id 0 in one version and table_id 1 in the
    # other, because an unrelated table was inserted above it. Matching by id
    # would pair the wrong tables entirely.
    old_grids = build_grids([
        cell(0, 0, 0, "Assay"), cell(0, 0, 1, "95 percent"),
        cell(0, 1, 0, "Water"), cell(0, 1, 1, "2.0 percent"),
    ])
    new_grids = build_grids([
        cell(0, 0, 0, "Unrelated"), cell(0, 0, 1, "New table entirely"),
        cell(1, 0, 0, "Assay"), cell(1, 0, 1, "98 percent"),
        cell(1, 1, 0, "Water"), cell(1, 1, 1, "2.0 percent"),
    ])

    pairs = match_tables(old_grids, new_grids)

    assert len(pairs) == 1
    old_grid, new_grid = pairs[0]
    assert old_grid.table_id == 0
    assert new_grid.table_id == 1


def test_match_lines_matches_an_edited_line_and_ignores_position():
    old_texts = ["Param | Spec", "Assay | 95%", "Water | 2.0%"]
    new_texts = ["Param | Spec", "Water | 2.0%", "Assay | 98%"]

    pairs = _match_lines(old_texts, new_texts)
    by_old = {i: j for i, j, _ in pairs}

    # The edited Assay line still matches, and Water matches despite moving.
    assert by_old == {0: 0, 1: 2, 2: 1}


def _grids(old_cells, new_cells):
    return build_grids(old_cells)[0], build_grids(new_cells)[0]


def _merges(old_grid, new_grid):
    # diff_merges compares aligned positions, so it needs the alignments the
    # other two detectors compute. Mirrors what detect_table_structure_changes does.
    _row_changes, _row_excluded, row_alignment = diff_rows(old_grid, new_grid)
    _col_changes, _col_excluded, col_alignment = diff_columns(old_grid, new_grid, row_alignment)
    return diff_merges(old_grid, new_grid, row_alignment, col_alignment)


def test_row_added_is_reported_once_with_the_whole_row():
    old_grid, new_grid = _grids(
        [cell(0, 0, 0, "Param"), cell(0, 0, 1, "Spec"),
         cell(0, 1, 0, "Assay"), cell(0, 1, 1, "95 percent")],
        [cell(0, 0, 0, "Param"), cell(0, 0, 1, "Spec"),
         cell(0, 1, 0, "Assay"), cell(0, 1, 1, "95 percent"),
         cell(0, 2, 0, "Hardness"), cell(0, 2, 1, "8 kg")],
    )

    changes, excluded, _alignment = diff_rows(old_grid, new_grid)

    added = [c for c in changes if c.change_type == "table_row_added"]
    assert len(added) == 1
    assert added[0].new_text == "Hardness | 8 kg"
    assert added[0].source == "Table"
    assert added[0].ai_risk_level == "Medium"
    # Both cells of the added row are excluded, so they are not also reported
    # individually as added_table_content.
    assert len(excluded) == 2


def test_row_deleted_is_reported_once_and_its_cells_excluded():
    old_grid, new_grid = _grids(
        [cell(0, 0, 0, "Param"), cell(0, 0, 1, "Spec"),
         cell(0, 1, 0, "Assay"), cell(0, 1, 1, "95 percent"),
         cell(0, 2, 0, "Hardness"), cell(0, 2, 1, "8 kg")],
        [cell(0, 0, 0, "Param"), cell(0, 0, 1, "Spec"),
         cell(0, 1, 0, "Assay"), cell(0, 1, 1, "95 percent")],
    )

    changes, excluded, _alignment = diff_rows(old_grid, new_grid)

    deleted = [c for c in changes if c.change_type == "table_row_deleted"]
    assert len(deleted) == 1
    assert deleted[0].old_text == "Hardness | 8 kg"
    assert len(excluded) == 2


def test_row_moved_is_reported_and_its_cells_are_not_excluded():
    # A move must not suppress anything: if a cell in the moved row was also
    # edited, that edit still has to reach the report.
    old_grid, new_grid = _grids(
        [cell(0, 0, 0, "Param"), cell(0, 0, 1, "Spec"),
         cell(0, 1, 0, "Assay"), cell(0, 1, 1, "95 percent"),
         cell(0, 2, 0, "Water"), cell(0, 2, 1, "2.0 percent")],
        [cell(0, 0, 0, "Param"), cell(0, 0, 1, "Spec"),
         cell(0, 1, 0, "Water"), cell(0, 1, 1, "2.0 percent"),
         cell(0, 2, 0, "Assay"), cell(0, 2, 1, "95 percent")],
    )

    changes, excluded, _alignment = diff_rows(old_grid, new_grid)

    moved = [c for c in changes if c.change_type == "table_row_moved"]
    assert len(moved) == 1
    assert moved[0].ai_risk_level == "Informational"
    assert excluded == set()


def test_row_whose_cells_were_edited_is_matched_not_added_and_deleted():
    # The central rule: an edited row is still the same row. Reporting it as a
    # delete plus an add would be worse than today's behaviour.
    old_grid, new_grid = _grids(
        [cell(0, 0, 0, "Param"), cell(0, 0, 1, "Spec"),
         cell(0, 1, 0, "Assay"), cell(0, 1, 1, "95 percent")],
        [cell(0, 0, 0, "Param"), cell(0, 0, 1, "Spec"),
         cell(0, 1, 0, "Assay"), cell(0, 1, 1, "98 percent")],
    )

    changes, excluded, _alignment = diff_rows(old_grid, new_grid)

    assert changes == []
    assert excluded == set()


def test_column_added_is_reported_once_with_the_whole_column():
    old_grid, new_grid = _grids(
        [cell(0, 0, 0, "Param"), cell(0, 0, 1, "Spec"),
         cell(0, 1, 0, "Assay"), cell(0, 1, 1, "95 percent")],
        [cell(0, 0, 0, "Param"), cell(0, 0, 1, "Spec"), cell(0, 0, 2, "Method"),
         cell(0, 1, 0, "Assay"), cell(0, 1, 1, "95 percent"), cell(0, 1, 2, "HPLC")],
    )

    _row_changes, _row_excluded, row_alignment = diff_rows(old_grid, new_grid)
    changes, excluded, _col_alignment = diff_columns(old_grid, new_grid, row_alignment)

    added = [c for c in changes if c.change_type == "table_column_added"]
    assert len(added) == 1
    assert added[0].new_text == "Method | HPLC"
    assert added[0].ai_risk_level == "Medium"
    assert len(excluded) == 2


def test_column_deleted_is_reported_once_and_its_cells_excluded():
    old_grid, new_grid = _grids(
        [cell(0, 0, 0, "Param"), cell(0, 0, 1, "Spec"), cell(0, 0, 2, "Method"),
         cell(0, 1, 0, "Assay"), cell(0, 1, 1, "95 percent"), cell(0, 1, 2, "HPLC")],
        [cell(0, 0, 0, "Param"), cell(0, 0, 1, "Spec"),
         cell(0, 1, 0, "Assay"), cell(0, 1, 1, "95 percent")],
    )

    _row_changes, _row_excluded, row_alignment = diff_rows(old_grid, new_grid)
    changes, excluded, _col_alignment = diff_columns(old_grid, new_grid, row_alignment)

    deleted = [c for c in changes if c.change_type == "table_column_deleted"]
    assert len(deleted) == 1
    assert deleted[0].old_text == "Method | HPLC"
    assert len(excluded) == 2


def test_column_moved_is_reported_and_its_cells_are_not_excluded():
    old_grid, new_grid = _grids(
        [cell(0, 0, 0, "Param"), cell(0, 0, 1, "Spec"), cell(0, 0, 2, "Method"),
         cell(0, 1, 0, "Assay"), cell(0, 1, 1, "95 percent"), cell(0, 1, 2, "HPLC")],
        [cell(0, 0, 0, "Param"), cell(0, 0, 1, "Method"), cell(0, 0, 2, "Spec"),
         cell(0, 1, 0, "Assay"), cell(0, 1, 1, "HPLC"), cell(0, 1, 2, "95 percent")],
    )

    _row_changes, _row_excluded, row_alignment = diff_rows(old_grid, new_grid)
    changes, excluded, _col_alignment = diff_columns(old_grid, new_grid, row_alignment)

    moved = [c for c in changes if c.change_type == "table_column_moved"]
    assert len(moved) == 1
    assert moved[0].ai_risk_level == "Informational"
    assert excluded == set()


def test_newly_merged_cell_is_reported():
    old_grid, new_grid = _grids(
        [cell(0, 0, 0, "Limit"), cell(0, 0, 1, "Limit")],
        [cell(0, 0, 0, "Limit", col_span=2)],
    )

    changes = _merges(old_grid, new_grid)

    assert len(changes) == 1
    assert changes[0].change_type == "table_cell_merge_changed"
    assert changes[0].ai_risk_level == "Informational"


def test_unmerged_cell_is_reported():
    old_grid, new_grid = _grids(
        [cell(0, 0, 0, "Limit", row_span=2)],
        [cell(0, 0, 0, "Limit"), cell(0, 1, 0, "Limit")],
    )

    changes = _merges(old_grid, new_grid)

    assert len(changes) == 1
    assert changes[0].change_type == "table_cell_merge_changed"


def test_unchanged_spans_report_nothing():
    old_grid, new_grid = _grids(
        [cell(0, 0, 0, "Limit", col_span=2), cell(0, 1, 0, "Assay")],
        [cell(0, 0, 0, "Limit", col_span=2), cell(0, 1, 0, "Assay")],
    )

    assert _merges(old_grid, new_grid) == []


def test_entry_point_matches_tables_by_content_despite_shifted_ids():
    # The Assay table is table_id 0 in old and table_id 1 in new, because an
    # unrelated table was inserted above it. Its added row must still be found.
    old_paragraphs = [
        cell(0, 0, 0, "Assay"), cell(0, 0, 1, "95 percent"),
    ]
    new_paragraphs = [
        cell(0, 0, 0, "Unrelated"), cell(0, 0, 1, "Entirely different table"),
        cell(1, 0, 0, "Assay"), cell(1, 0, 1, "95 percent"),
        cell(1, 1, 0, "Hardness"), cell(1, 1, 1, "8 kg"),
    ]

    changes, excluded = detect_table_structure_changes(old_paragraphs, new_paragraphs)

    added = [c for c in changes if c.change_type == "table_row_added"]
    assert len(added) == 1
    assert added[0].new_text == "Hardness | 8 kg"


def test_entry_point_returns_nothing_when_there_are_no_tables():
    changes, excluded = detect_table_structure_changes(
        [Paragraph(text="body text")], [Paragraph(text="body text")]
    )

    assert changes == []
    assert excluded == set()


def test_structural_changes_carry_table_identity():
    # A structural row used to carry section="" and no coordinates, which left
    # a blank entry in the section filter and crashed the Detailed Changes page.
    old_grid, new_grid = _grids(
        [cell(0, 0, 0, "Param"), cell(0, 0, 1, "Spec")],
        [cell(0, 0, 0, "Param"), cell(0, 0, 1, "Spec"),
         cell(0, 1, 0, "Hardness"), cell(0, 1, 1, "8 kg")],
    )

    changes, _excluded, _alignment = diff_rows(old_grid, new_grid)

    added = [c for c in changes if c.change_type == "table_row_added"][0]
    assert added.section == "Table 1"
    assert added.new_table_position is not None
    assert added.new_table_position.table_id == 0
    assert added.new_table_position.row == 1


def test_deleted_row_carries_only_an_old_position():
    old_grid, new_grid = _grids(
        [cell(0, 0, 0, "Param"), cell(0, 0, 1, "Spec"),
         cell(0, 1, 0, "Hardness"), cell(0, 1, 1, "8 kg")],
        [cell(0, 0, 0, "Param"), cell(0, 0, 1, "Spec")],
    )

    changes, _excluded, _alignment = diff_rows(old_grid, new_grid)

    deleted = [c for c in changes if c.change_type == "table_row_deleted"][0]
    assert deleted.section == "Table 1"
    assert deleted.old_table_position.row == 1
    assert deleted.new_table_position is None


def test_moved_row_carries_both_positions():
    old_grid, new_grid = _grids(
        [cell(0, 0, 0, "Param"), cell(0, 0, 1, "Spec"),
         cell(0, 1, 0, "Assay"), cell(0, 1, 1, "95 percent"),
         cell(0, 2, 0, "Water"), cell(0, 2, 1, "2.0 percent")],
        [cell(0, 0, 0, "Param"), cell(0, 0, 1, "Spec"),
         cell(0, 1, 0, "Water"), cell(0, 1, 1, "2.0 percent"),
         cell(0, 2, 0, "Assay"), cell(0, 2, 1, "95 percent")],
    )

    changes, _excluded, _alignment = diff_rows(old_grid, new_grid)

    moved = [c for c in changes if c.change_type == "table_row_moved"][0]
    assert moved.old_table_position.row == 2
    assert moved.new_table_position.row == 1


def test_column_changes_carry_a_column_coordinate():
    old_grid, new_grid = _grids(
        [cell(0, 0, 0, "Param"), cell(0, 0, 1, "Spec"), cell(0, 0, 2, "Method"),
         cell(0, 1, 0, "Assay"), cell(0, 1, 1, "95 percent"), cell(0, 1, 2, "HPLC")],
        [cell(0, 0, 0, "Param"), cell(0, 0, 1, "Spec"),
         cell(0, 1, 0, "Assay"), cell(0, 1, 1, "95 percent")],
    )

    _row_changes, _row_excluded, row_alignment = diff_rows(old_grid, new_grid)
    changes, _excluded, _col_alignment = diff_columns(old_grid, new_grid, row_alignment)

    deleted = [c for c in changes if c.change_type == "table_column_deleted"][0]
    assert deleted.section == "Table 1"
    assert deleted.old_table_position.col == 2
    assert deleted.new_table_position is None


def _table(rows, table_id=0):
    return [
        cell(table_id, row_index, col_index, text)
        for row_index, row in enumerate(rows)
        for col_index, text in enumerate(row)
    ]


_THREE_COLUMN_TABLE = [
    ["Parameter", "Specification", "Method"],
    ["Assay", "95.0 to 105.0 percent", "HPLC"],
    ["Water content", "Not more than 2.0 percent", "Karl Fischer"],
]

_TWO_COLUMN_TABLE = [row[:2] for row in _THREE_COLUMN_TABLE]


def test_deleting_a_column_does_not_split_rows():
    # 3-column table loses its Method column; rows are otherwise untouched.
    # Matching rows on full-width text pushed them across the 0.85 threshold
    # and produced two false row deletes plus two false row adds.
    changes, _excluded = detect_table_structure_changes(
        _table(_THREE_COLUMN_TABLE), _table(_TWO_COLUMN_TABLE)
    )

    types = [c.change_type for c in changes]
    assert types.count("table_column_deleted") == 1
    assert "table_row_deleted" not in types
    assert "table_row_added" not in types


def test_adding_a_column_does_not_split_rows():
    changes, _excluded = detect_table_structure_changes(
        _table(_TWO_COLUMN_TABLE), _table(_THREE_COLUMN_TABLE)
    )

    types = [c.change_type for c in changes]
    assert types.count("table_column_added") == 1
    assert "table_row_deleted" not in types
    assert "table_row_added" not in types


def test_a_column_delete_does_not_suppress_an_edit_in_a_surviving_column():
    # The suppression rule cuts both ways: only the deleted column's own cells
    # may be excluded, never a cell that was independently edited.
    old_paragraphs = _table(_THREE_COLUMN_TABLE)
    new_paragraphs = _table([
        ["Parameter", "Specification"],
        ["Assay", "98.0 to 102.0 percent"],
        ["Water content", "Not more than 2.0 percent"],
    ])

    changes, excluded = detect_table_structure_changes(old_paragraphs, new_paragraphs)

    assert [c.change_type for c in changes] == ["table_column_deleted"]
    edited = [p for p in new_paragraphs if p.text == "98.0 to 102.0 percent"]
    assert id(edited[0]) not in excluded


def test_merge_detection_is_unaffected_by_an_inserted_row():
    # A row inserted ABOVE an untouched merged cell shifts its index. Comparing
    # raw indices compared two unrelated cells and invented a merge change.
    old_paragraphs = [
        cell(0, 0, 0, "Parameter"), cell(0, 0, 1, "Specification"),
        cell(0, 1, 0, "Assay"), cell(0, 1, 1, "95.0 percent"),
        cell(0, 2, 0, "Combined limits note", col_span=2),
    ]
    new_paragraphs = [
        cell(0, 0, 0, "Parameter"), cell(0, 0, 1, "Specification"),
        cell(0, 1, 0, "Hardness"), cell(0, 1, 1, "8 kg"),
        cell(0, 2, 0, "Assay"), cell(0, 2, 1, "95.0 percent"),
        cell(0, 3, 0, "Combined limits note", col_span=2),
    ]

    changes, _excluded = detect_table_structure_changes(old_paragraphs, new_paragraphs)

    types = [c.change_type for c in changes]
    assert types.count("table_cell_merge_changed") == 0
    assert types.count("table_row_added") == 1


def test_a_genuine_merge_on_a_shifted_row_is_still_detected():
    # The false-negative half of the same bug: the real merge sat on a row whose
    # index moved, so raw comparison checked the wrong cell and missed it.
    old_paragraphs = [
        cell(0, 0, 0, "Parameter"), cell(0, 0, 1, "Specification"),
        cell(0, 1, 0, "Assay"), cell(0, 1, 1, "95.0 percent"),
        cell(0, 2, 0, "Combined limits note"), cell(0, 2, 1, "See appendix"),
    ]
    new_paragraphs = [
        cell(0, 0, 0, "Parameter"), cell(0, 0, 1, "Specification"),
        cell(0, 1, 0, "Hardness"), cell(0, 1, 1, "8 kg"),
        cell(0, 2, 0, "Assay"), cell(0, 2, 1, "95.0 percent"),
        cell(0, 3, 0, "Combined limits note", col_span=2),
    ]

    changes, _excluded = detect_table_structure_changes(old_paragraphs, new_paragraphs)

    merges = [c for c in changes if c.change_type == "table_cell_merge_changed"]
    assert len(merges) == 1
    assert merges[0].old_table_position.row == 2
    assert merges[0].new_table_position.row == 3


def test_introducing_a_merge_does_not_fake_a_column_delete_and_add():
    # A horizontal merge vacates a grid position, so the column reads as emptied
    # and its similarity collapsed below threshold (measured 0.706 and 0.753),
    # producing a Medium-risk false pair that outranked the correct merge row.
    old_paragraphs = [
        cell(0, 0, 0, "Analytical"), cell(0, 0, 1, "Results"),
        cell(0, 1, 0, "Assay"), cell(0, 1, 1, "95 percent"),
        cell(0, 2, 0, "Water"), cell(0, 2, 1, "2.0 percent"),
    ]
    new_paragraphs = [
        cell(0, 0, 0, "Analytical Results", col_span=2),
        cell(0, 1, 0, "Assay"), cell(0, 1, 1, "95 percent"),
        cell(0, 2, 0, "Water"), cell(0, 2, 1, "2.0 percent"),
    ]

    changes, excluded = detect_table_structure_changes(old_paragraphs, new_paragraphs)

    assert [c.change_type for c in changes] == ["table_cell_merge_changed"]
    assert excluded == set()


def test_identical_line_lists_short_circuit_to_an_identity_mapping():
    # Embedding two identical lists to rediscover an identity mapping dominated
    # the cost on a document whose tables were mostly untouched.
    texts = ["Param | Spec", "Assay | 95 percent", "Water | 2.0 percent"]

    assert _match_lines(texts, list(texts)) == [(0, 0, 1.0), (1, 1, 1.0), (2, 2, 1.0)]
