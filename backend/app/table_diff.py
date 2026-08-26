import uuid
from dataclasses import dataclass, field

from app import risk_rules
from app.embeddings import embed_texts, cosine_similarity_matrix
from app.matching import greedy_match
from app.models import Change, Paragraph, TableCoordinate
from app.section_structure import _longest_increasing_subsequence_indices

# Same threshold move_reconciliation uses. Rows are short, so genuinely
# different rows score far below this while an edited row scores well above -
# an edited row differing by one spec value measured 0.96 in prototyping.
LINE_MATCH_THRESHOLD = 0.85
TABLE_MATCH_THRESHOLD = 0.6


@dataclass
class TableGrid:
    table_id: int
    cells: dict[tuple[int, int], list[Paragraph]] = field(default_factory=dict)

    @property
    def rows(self) -> list[int]:
        return sorted({row for row, _ in self.cells})

    @property
    def cols(self) -> list[int]:
        return sorted({col for _, col in self.cells})

    def text_at(self, row: int, col: int) -> str:
        return " ".join(p.text for p in self.cells.get((row, col), []))

    def span_at(self, row: int, col: int) -> tuple[int, int]:
        paragraphs = self.cells.get((row, col))
        if not paragraphs:
            return 1, 1
        position = paragraphs[0].table_position
        return position.row_span, position.col_span

    def row_text(self, row: int, cols: list[int] | None = None) -> str:
        cols = self.cols if cols is None else cols
        return " | ".join(self.text_at(row, col) for col in cols)

    def col_text(self, col: int, rows: list[int] | None = None) -> str:
        rows = self.rows if rows is None else rows
        return " | ".join(self.text_at(row, col) for row in rows)

    def row_paragraphs(self, row: int) -> list[Paragraph]:
        return [p for col in self.cols for p in self.cells.get((row, col), [])]

    def col_paragraphs(self, col: int) -> list[Paragraph]:
        return [p for row in self.rows for p in self.cells.get((row, col), [])]

    def flat_text(self) -> str:
        return " | ".join(self.row_text(row) for row in self.rows)


def build_grids(paragraphs: list[Paragraph]) -> dict[int, TableGrid]:
    grids: dict[int, TableGrid] = {}
    for paragraph in paragraphs:
        position = paragraph.table_position
        if position is None:
            continue
        grid = grids.setdefault(position.table_id, TableGrid(table_id=position.table_id))
        grid.cells.setdefault((position.row, position.col), []).append(paragraph)
    return grids


def _match_lines(old_texts: list[str], new_texts: list[str]) -> list[tuple[int, int, float]]:
    # Similarity matching, not difflib. Sequence matching reports an edited line
    # and a moved line each as a delete plus an add, so neither is ever matched -
    # which loses both the move and the "edited lines stay matched" guarantee.
    if not old_texts or not new_texts:
        return []
    # Most tables in a revised document are untouched. Embedding two identical
    # lists to rediscover an identity mapping dominated the cost - measured
    # 8.54s -> 1.62s on a 40-table document with one cell changed, and the two
    # runs produced identical changes and identical exclusions.
    if old_texts == new_texts:
        return [(i, i, 1.0) for i in range(len(old_texts))]
    scores = cosine_similarity_matrix(embed_texts(old_texts), embed_texts(new_texts))
    return greedy_match(scores, LINE_MATCH_THRESHOLD)


def match_tables(
    old_grids: dict[int, TableGrid], new_grids: dict[int, TableGrid]
) -> list[tuple[TableGrid, TableGrid]]:
    # table_id is a global counter, so inserting any table earlier shifts every
    # later id. Matching by id would pair unrelated tables; match by content.
    old_list = [old_grids[k] for k in sorted(old_grids)]
    new_list = [new_grids[k] for k in sorted(new_grids)]
    if not old_list or not new_list:
        return []
    scores = cosine_similarity_matrix(
        embed_texts([g.flat_text() for g in old_list]),
        embed_texts([g.flat_text() for g in new_list]),
    )
    return [
        (old_list[i], new_list[j])
        for i, j, _ in greedy_match(scores, TABLE_MATCH_THRESHOLD)
    ]


def _line_change(
    change_type: str,
    old_text: str,
    new_text: str,
    reason: str,
    table_id: int,
    old_position: TableCoordinate | None = None,
    new_position: TableCoordinate | None = None,
) -> Change:
    # A structural change is still a change in a specific table. Leaving section
    # empty and both positions None left the reviewer unable to tell which table
    # moved, put a blank entry in the section filter, and made the Detailed
    # Changes page dereference a missing position while grouping Table rows.
    return Change(
        change_id=str(uuid.uuid4()), section=f"Table {table_id + 1}",
        change_type=change_type,
        old_text=old_text, new_text=new_text, old_page=None, new_page=None,
        confidence=1.0, ai_risk_level=risk_rules.assign_risk(change_type),
        reason=reason, source="Table",
        old_table_position=old_position, new_table_position=new_position,
    )


def diff_rows(
    old_grid: TableGrid,
    new_grid: TableGrid,
    old_cols: list[int] | None = None,
    new_cols: list[int] | None = None,
) -> tuple[list[Change], set[int], list[tuple[int, int]]]:
    # Rows are matched over a caller-chosen pair of column lists. Matching on
    # full-width row text made a column add or delete shift every row's text and
    # push similarity unpredictably across the threshold (measured 0.734-0.925),
    # splitting untouched rows into false delete+add pairs. Comparing only the
    # columns that survive in both versions leaves those rows matching at 1.00.
    # Reported text stays full width - the reviewer wants to see the whole row.
    old_cols = old_grid.cols if old_cols is None else old_cols
    new_cols = new_grid.cols if new_cols is None else new_cols
    old_rows, new_rows = old_grid.rows, new_grid.rows
    pairs = _match_lines(
        [old_grid.row_text(r, old_cols) for r in old_rows],
        [new_grid.row_text(r, new_cols) for r in new_rows],
    )
    matched_old = {i for i, _, _ in pairs}
    matched_new = {j for _, j, _ in pairs}

    changes: list[Change] = []
    excluded: set[int] = set()

    for index, row in enumerate(old_rows):
        if index in matched_old:
            continue
        changes.append(_line_change(
            "table_row_deleted", old_grid.row_text(row), "",
            f"Table row {row + 1} removed.",
            new_grid.table_id,
            old_position=TableCoordinate(table_id=old_grid.table_id, row=row, col=0),
        ))
        excluded.update(id(p) for p in old_grid.row_paragraphs(row))

    for index, row in enumerate(new_rows):
        if index in matched_new:
            continue
        changes.append(_line_change(
            "table_row_added", "", new_grid.row_text(row),
            f"Table row {row + 1} added.",
            new_grid.table_id,
            new_position=TableCoordinate(table_id=new_grid.table_id, row=row, col=0),
        ))
        excluded.update(id(p) for p in new_grid.row_paragraphs(row))

    # A matched row sitting outside the longest increasing subsequence of new
    # positions has moved. Its cells are deliberately NOT excluded - a move must
    # never suppress an edit to a cell inside the row that moved.
    ordered = sorted(pairs)
    kept = _longest_increasing_subsequence_indices([j for _, j, _ in ordered])
    for position, (i, j, _score) in enumerate(ordered):
        if position in kept:
            continue
        changes.append(_line_change(
            "table_row_moved", old_grid.row_text(old_rows[i]), new_grid.row_text(new_rows[j]),
            f"Table row moved from position {old_rows[i] + 1} to position {new_rows[j] + 1}.",
            new_grid.table_id,
            old_position=TableCoordinate(table_id=old_grid.table_id, row=old_rows[i], col=0),
            new_position=TableCoordinate(table_id=new_grid.table_id, row=new_rows[j], col=0),
        ))

    row_alignment = [(old_rows[i], new_rows[j]) for i, j, _ in ordered]
    return changes, excluded, row_alignment


def _spans_differ(
    old_grid: TableGrid, new_grid: TableGrid, old_row: int, new_row: int
) -> bool:
    for col in sorted(set(old_grid.cols) | set(new_grid.cols)):
        if old_grid.span_at(old_row, col) != new_grid.span_at(new_row, col):
            return True
    return False


def diff_columns(
    old_grid: TableGrid, new_grid: TableGrid, row_alignment: list[tuple[int, int]]
) -> tuple[list[Change], set[int], list[tuple[int, int]]]:
    old_cols, new_cols = old_grid.cols, new_grid.cols
    # Compare columns only over rows that matched. Including an added or deleted
    # row drags every column's similarity down - a real table scored its edited
    # Limit column at 0.80 (below threshold, so a false delete+add pair) which
    # rose to 0.94 once the added row was excluded from the comparison.
    #
    # Rows whose spans changed are dropped too. A merge vacates a grid position,
    # so a column that gained or lost a merge reads as emptied and falls under
    # threshold - measured 0.706 and 0.753, producing a false delete+add pair
    # that outranks the correct merge row on risk. Comparing only rows whose
    # spans are unchanged sidesteps it; diff_merges reports the merge itself.
    # Fall back to the full alignment when every row changed spans, so such a
    # table still compares something.
    comparable = [
        (old_row, new_row) for old_row, new_row in row_alignment
        if not _spans_differ(old_grid, new_grid, old_row, new_row)
    ] or row_alignment
    aligned_old = [r for r, _ in comparable]
    aligned_new = [r for _, r in comparable]
    pairs = _match_lines(
        [old_grid.col_text(c, aligned_old) for c in old_cols],
        [new_grid.col_text(c, aligned_new) for c in new_cols],
    )
    matched_old = {i for i, _, _ in pairs}
    matched_new = {j for _, j, _ in pairs}

    changes: list[Change] = []
    excluded: set[int] = set()

    for index, col in enumerate(old_cols):
        if index in matched_old:
            continue
        changes.append(_line_change(
            "table_column_deleted", old_grid.col_text(col), "",
            f"Table column {col + 1} removed.",
            new_grid.table_id,
            old_position=TableCoordinate(table_id=old_grid.table_id, row=0, col=col),
        ))
        excluded.update(id(p) for p in old_grid.col_paragraphs(col))

    for index, col in enumerate(new_cols):
        if index in matched_new:
            continue
        changes.append(_line_change(
            "table_column_added", "", new_grid.col_text(col),
            f"Table column {col + 1} added.",
            new_grid.table_id,
            new_position=TableCoordinate(table_id=new_grid.table_id, row=0, col=col),
        ))
        excluded.update(id(p) for p in new_grid.col_paragraphs(col))

    ordered = sorted(pairs)
    kept = _longest_increasing_subsequence_indices([j for _, j, _ in ordered])
    for position, (i, j, _score) in enumerate(ordered):
        if position in kept:
            continue
        changes.append(_line_change(
            "table_column_moved", old_grid.col_text(old_cols[i]), new_grid.col_text(new_cols[j]),
            f"Table column moved from position {old_cols[i] + 1} to position {new_cols[j] + 1}.",
            new_grid.table_id,
            old_position=TableCoordinate(table_id=old_grid.table_id, row=0, col=old_cols[i]),
            new_position=TableCoordinate(table_id=new_grid.table_id, row=0, col=new_cols[j]),
        ))

    col_alignment = [(old_cols[i], new_cols[j]) for i, j, _ in ordered]
    return changes, excluded, col_alignment


def diff_merges(
    old_grid: TableGrid,
    new_grid: TableGrid,
    row_alignment: list[tuple[int, int]],
    col_alignment: list[tuple[int, int]],
) -> list[Change]:
    # Compare aligned positions, not raw (row, col) indices. Any inserted row or
    # column shifts every later index, so raw comparison pitted unrelated cells
    # against each other - inventing merge changes, and worse, missing genuine
    # ones because the changed cell was compared against the wrong neighbour.
    # Positions outside both alignments belong to rows or columns already
    # reported as added or deleted, so nothing is lost by skipping them.
    changes: list[Change] = []
    for old_row, new_row in row_alignment:
        for old_col, new_col in col_alignment:
            old_span = old_grid.span_at(old_row, old_col)
            new_span = new_grid.span_at(new_row, new_col)
            if old_span == new_span:
                continue
            changes.append(_line_change(
                "table_cell_merge_changed",
                old_grid.text_at(old_row, old_col), new_grid.text_at(new_row, new_col),
                f"Table cell at row {new_row + 1}, column {new_col + 1} changed from spanning "
                f"{old_span[0]}x{old_span[1]} to {new_span[0]}x{new_span[1]} cells.",
                new_grid.table_id,
                old_position=TableCoordinate(
                    table_id=old_grid.table_id, row=old_row, col=old_col,
                    row_span=old_span[0], col_span=old_span[1],
                ),
                new_position=TableCoordinate(
                    table_id=new_grid.table_id, row=new_row, col=new_col,
                    row_span=new_span[0], col_span=new_span[1],
                ),
            ))
    return changes


def detect_table_structure_changes(
    old_paragraphs: list[Paragraph], new_paragraphs: list[Paragraph]
) -> tuple[list[Change], set[int]]:
    changes: list[Change] = []
    excluded: set[int] = set()
    for old_grid, new_grid in match_tables(build_grids(old_paragraphs), build_grids(new_paragraphs)):
        # Rows are matched twice. The first pass is rough - it compares full-width
        # row text, which a column add or delete distorts - but it is good enough
        # to tell diff_columns which rows correspond. The column result then names
        # the columns that survive in both versions, and rows are re-matched over
        # only those, which is the pass that gets reported.
        rough_changes, rough_excluded, rough_alignment = diff_rows(old_grid, new_grid)
        column_changes, column_excluded, col_alignment = diff_columns(
            old_grid, new_grid, rough_alignment
        )
        if col_alignment:
            # Pair surviving columns through the alignment rather than by ordinal
            # position, so a column that moved still compares against its own
            # content in the other version.
            row_changes, row_excluded, row_alignment = diff_rows(
                old_grid, new_grid,
                [c for c, _ in col_alignment], [c for _, c in col_alignment],
            )
        else:
            # No column survives in both versions, so there is nothing to compare
            # rows over - every row text would be empty and every row would match
            # every other. Keep the full-width first pass.
            row_changes, row_excluded, row_alignment = (
                rough_changes, rough_excluded, rough_alignment
            )
        changes.extend(row_changes)
        changes.extend(column_changes)
        changes.extend(diff_merges(old_grid, new_grid, row_alignment, col_alignment))
        excluded.update(row_excluded)
        excluded.update(column_excluded)
    return changes, excluded
