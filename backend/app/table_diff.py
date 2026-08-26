from dataclasses import dataclass, field

from app.embeddings import embed_texts, cosine_similarity_matrix
from app.matching import greedy_match
from app.models import Paragraph

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
