from app.models import Paragraph, TableCoordinate
from app.table_diff import build_grids, match_tables, _match_lines, diff_rows


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
