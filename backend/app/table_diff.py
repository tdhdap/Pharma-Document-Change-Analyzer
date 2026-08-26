import uuid
from dataclasses import dataclass, field

from app import risk_rules
from app.embeddings import embed_texts, cosine_similarity_matrix
from app.matching import greedy_match
from app.models import Change, Paragraph
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

    def row_text(self, row: int) -> str:
        return " | ".join(self.text_at(row, col) for col in self.cols)

    def col_text(self, col: int) -> str:
        return " | ".join(self.text_at(row, col) for row in self.rows)

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


def _line_change(change_type: str, old_text: str, new_text: str, reason: str) -> Change:
    return Change(
        change_id=str(uuid.uuid4()), section="", change_type=change_type,
        old_text=old_text, new_text=new_text, old_page=None, new_page=None,
        confidence=1.0, ai_risk_level=risk_rules.assign_risk(change_type),
        reason=reason, source="Table",
    )


def diff_rows(
    old_grid: TableGrid, new_grid: TableGrid
) -> tuple[list[Change], set[int], list[tuple[int, int]]]:
    old_rows, new_rows = old_grid.rows, new_grid.rows
    pairs = _match_lines(
        [old_grid.row_text(r) for r in old_rows],
        [new_grid.row_text(r) for r in new_rows],
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
        ))
        excluded.update(id(p) for p in old_grid.row_paragraphs(row))

    for index, row in enumerate(new_rows):
        if index in matched_new:
            continue
        changes.append(_line_change(
            "table_row_added", "", new_grid.row_text(row),
            f"Table row {row + 1} added.",
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
        ))

    row_alignment = [(old_rows[i], new_rows[j]) for i, j, _ in ordered]
    return changes, excluded, row_alignment


def diff_columns(
    old_grid: TableGrid, new_grid: TableGrid, row_alignment: list[tuple[int, int]]
) -> tuple[list[Change], set[int]]:
    old_cols, new_cols = old_grid.cols, new_grid.cols
    # Compare columns only over rows that matched. Including an added or deleted
    # row drags every column's similarity down - a real table scored its edited
    # Limit column at 0.80 (below threshold, so a false delete+add pair) which
    # rose to 0.94 once the added row was excluded from the comparison.
    aligned_old = [r for r, _ in row_alignment]
    aligned_new = [r for _, r in row_alignment]
    pairs = _match_lines(
        [" | ".join(old_grid.text_at(r, c) for r in aligned_old) for c in old_cols],
        [" | ".join(new_grid.text_at(r, c) for r in aligned_new) for c in new_cols],
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
        ))
        excluded.update(id(p) for p in old_grid.col_paragraphs(col))

    for index, col in enumerate(new_cols):
        if index in matched_new:
            continue
        changes.append(_line_change(
            "table_column_added", "", new_grid.col_text(col),
            f"Table column {col + 1} added.",
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
        ))

    return changes, excluded
