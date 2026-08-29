# Table Structure Diffing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Report structural table edits as structural facts — a row or column added, deleted, or moved, and cells merged or unmerged — instead of as N unrelated per-cell changes.

**Architecture:** Extraction first gains merge spans, which nothing currently captures. A new `table_diff.py` then rebuilds each table into a grid, matches tables between versions by content (never by `table_id`, which is unstable), and matches rows and columns by embedding similarity — the same machinery that already matches sections and reconciles moved paragraphs. Matched-but-relocated lines become moves via the existing LIS logic. The pipeline appends the resulting changes and suppresses the per-cell changes belonging to added or deleted lines.

**Tech Stack:** Python, FastAPI backend, python-docx, sentence-transformers embeddings, pytest.

## Global Constraints

- **Never key tables by `table_id` across versions.** It is a global counter, so inserting a table earlier shifts every later id — verified: the same table was `table_id=0` in one version and `table_id=1` in another differing only by an unrelated table above it. Tables must be matched by content. (spec: "What exists today, verified")
- **Rows and columns are matched by similarity, not `difflib.SequenceMatcher`** — `embed_texts` + `cosine_similarity_matrix` + `greedy_match` at threshold `0.85`. Sequence matching was prototyped and fails: it reports an edited row and a moved row each as a delete plus an add, so neither is matchable. (spec: "Stage 3")
- **An edited row or column stays matched.** Its cell edits flow through the existing per-cell path unchanged; only genuinely new or removed lines produce structural changes. (spec: "Stage 3")
- **Suppression is narrow.** A cell is excluded only when its sole reason for changing is that its whole row or column was added or deleted. A line that moved *and* had a cell edited reports both. (spec: "Suppression")
- **Spans default to `1`** on `TableCoordinate` and are **not persisted** — `repository` flattens only `table_id`/`row`/`col`. No database migration. (spec: "backend/app/models.py")
- **Span counting needs a pre-pass that holds every cell proxy alive.** Keying on `id()` without holding references silently reports merged positions as distinct elements. (spec: "backend/app/extraction.py")
- Risk: `table_row_added`, `table_row_deleted`, `table_column_added`, `table_column_deleted` are **Medium**; `table_row_moved`, `table_column_moved`, `table_cell_merge_changed` are **Informational**. Each needs an explicit `RISK_TABLE` entry or it falls through to `DEFAULT_RISK` of `"Medium"`. (spec: "New change types and risk")
- Out of scope: whole tables added/removed as a structural type, fixing the displayed `table_id`, table formatting, and any change to how cell *content* is compared. (spec: "Out of Scope")

---

### Task 1: Capture merge spans during extraction

**Files:**
- Modify: `backend/app/models.py` (`TableCoordinate`)
- Modify: `backend/app/extraction.py` (`_iter_docx_paragraphs`)
- Test: `backend/tests/test_extraction.py`

**Interfaces:**
- Produces: `TableCoordinate` with two new fields, `row_span: int = 1` and `col_span: int = 1`. Every later task reads spans from `paragraph.table_position.row_span` / `.col_span`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_extraction.py`:

```python
def test_merge_spans_are_captured_for_both_directions(tmp_path):
    # row.cells returns a merged cell once per grid position it occupies, and all
    # those proxies wrap one w:tc element - so counting distinct row and column
    # indices per element gives both spans with one mechanism.
    file_path = tmp_path / "merged.docx"
    doc = DocxDocument()
    table = doc.add_table(rows=3, cols=3)
    for r in range(3):
        for c in range(3):
            table.rows[r].cells[c].text = f"r{r}c{c}"
    table.rows[0].cells[0].merge(table.rows[0].cells[1])   # horizontal, span 2
    table.rows[1].cells[2].merge(table.rows[2].cells[2])   # vertical, span 2
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")
    spans = {
        (p.table_position.row, p.table_position.col):
            (p.table_position.row_span, p.table_position.col_span)
        for p in paragraphs if p.table_position is not None
    }

    assert spans[(0, 0)] == (1, 2)
    assert spans[(1, 2)] == (2, 1)
    assert spans[(1, 0)] == (1, 1)
    assert spans[(2, 0)] == (1, 1)


def test_unmerged_table_cells_all_have_span_one(tmp_path):
    file_path = tmp_path / "plain.docx"
    doc = DocxDocument()
    table = doc.add_table(rows=2, cols=2)
    for r in range(2):
        for c in range(2):
            table.rows[r].cells[c].text = f"r{r}c{c}"
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")
    positions = [p.table_position for p in paragraphs if p.table_position is not None]

    assert len(positions) == 4
    assert all(pos.row_span == 1 and pos.col_span == 1 for pos in positions)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && python -m pytest tests/test_extraction.py -k merge_spans -v`
Expected: FAIL with `AttributeError: 'TableCoordinate' object has no attribute 'row_span'`.

- [ ] **Step 3: Add the span fields**

In `backend/app/models.py`, find:

```python
class TableCoordinate:
    table_id: int
    row: int
    col: int
```

Replace with:

```python
class TableCoordinate:
    table_id: int
    row: int
    col: int
    # Defaults keep every existing construction site, every row reloaded by
    # repository._row_to_change, and the PDF/TXT paths working untouched. Spans
    # are used only during table diffing and are deliberately not persisted.
    row_span: int = 1
    col_span: int = 1
```

- [ ] **Step 4: Populate spans in extraction**

In `backend/app/extraction.py`, inside `_iter_docx_paragraphs`, find:

```python
        elif isinstance(item, DocxTable):
            table_id = next(table_id_counter)
            seen_cells = set()
            for row_index, row in enumerate(item.rows):
                for col_index, cell in enumerate(row.cells):
```

Replace with:

```python
        elif isinstance(item, DocxTable):
            table_id = next(table_id_counter)
            # Pre-pass: a merged cell's span is the number of distinct grid rows and
            # columns its single w:tc element occupies. It cannot be read at the
            # anchor, because the positions it also occupies have not been visited
            # yet - and w:vMerge records only restart/continue, never a count.
            #
            # cell_proxies holds every proxy alive for the duration. lxml only
            # guarantees a stable identity for an element while some reference to
            # its proxy exists, and python-docx re-derives a vertically merged
            # cell's _tc on each lookup - without this, merged positions read as
            # distinct elements and every span comes back as 1.
            cell_proxies = [list(r.cells) for r in item.rows]
            rows_by_element: dict = {}
            cols_by_element: dict = {}
            for r_index, proxy_row in enumerate(cell_proxies):
                for c_index, proxy in enumerate(proxy_row):
                    rows_by_element.setdefault(proxy._tc, set()).add(r_index)
                    cols_by_element.setdefault(proxy._tc, set()).add(c_index)
            seen_cells = set()
            for row_index, row in enumerate(item.rows):
                for col_index, cell in enumerate(row.cells):
```

Then find the line that builds the coordinate:

```python
                    position = TableCoordinate(table_id=table_id, row=row_index, col=col_index)
```

Replace with:

```python
                    position = TableCoordinate(
                        table_id=table_id, row=row_index, col=col_index,
                        row_span=len(rows_by_element.get(cell._tc, {row_index})),
                        col_span=len(cols_by_element.get(cell._tc, {col_index})),
                    )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_extraction.py -q`
Expected: all pass, including the two new tests.

- [ ] **Step 6: Run the full backend suite**

Run: `cd backend && python -m pytest -q`
Expected: all pass. Existing tests construct `TableCoordinate` with three arguments and are unaffected by the defaulted fields.

- [ ] **Step 7: Commit**

```bash
git add backend/app/models.py backend/app/extraction.py backend/tests/test_extraction.py
git commit -m "feat: capture table cell merge spans during extraction"
```

---

### Task 2: Grid reconstruction and table matching

**Files:**
- Create: `backend/app/table_diff.py`
- Create: `backend/tests/test_table_diff.py`

**Interfaces:**
- Consumes: `TableCoordinate.row_span` / `.col_span` from Task 1.
- Produces: `TableGrid` dataclass with fields `table_id: int`, `cells: dict[tuple[int, int], list[Paragraph]]`, `rows: list[int]`, `cols: list[int]`, and methods `text_at(row, col) -> str`, `span_at(row, col) -> tuple[int, int]`, `row_text(row) -> str`, `col_text(col) -> str`, `flat_text() -> str`.
- Produces: `build_grids(paragraphs: list[Paragraph]) -> dict[int, TableGrid]`.
- Produces: `match_tables(old_grids, new_grids) -> list[tuple[TableGrid, TableGrid]]`.
- Produces: `_match_lines(old_texts: list[str], new_texts: list[str]) -> list[tuple[int, int, float]]` — shared similarity matcher used by Tasks 3 and 4.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_table_diff.py`:

```python
from app.models import Paragraph, TableCoordinate
from app.table_diff import build_grids, match_tables, _match_lines


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
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd backend && python -m pytest tests/test_table_diff.py -q`
Expected: FAIL at collection with `ModuleNotFoundError: No module named 'app.table_diff'`.

- [ ] **Step 3: Create the module**

Create `backend/app/table_diff.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_table_diff.py -q`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/table_diff.py backend/tests/test_table_diff.py
git commit -m "feat: add table grid reconstruction and content-based table matching"
```

---

### Task 3: Detect rows added, deleted, and moved

**Files:**
- Modify: `backend/app/table_diff.py`
- Modify: `backend/app/risk_rules.py`
- Test: `backend/tests/test_table_diff.py`
- Test: `backend/tests/test_risk_rules.py`

**Interfaces:**
- Consumes: `TableGrid`, `build_grids`, `_match_lines` from Task 2.
- Produces: `diff_rows(old_grid: TableGrid, new_grid: TableGrid) -> tuple[list[Change], set[int], list[tuple[int, int]]]` — the changes; the `id()` of every `Paragraph` belonging to an added or deleted row, for suppression; and the **row alignment** as `(old_row_index, new_row_index)` pairs in grid-index terms. Task 4 requires that alignment — comparing columns without it produces false delete+add pairs on real documents.

- [ ] **Step 1: Write the failing risk test**

Append to `backend/tests/test_risk_rules.py`:

```python
def test_table_row_change_types_have_explicit_risk():
    assert assign_risk("table_row_added") == "Medium"
    assert assign_risk("table_row_deleted") == "Medium"
    assert assign_risk("table_row_moved") == "Informational"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && python -m pytest tests/test_risk_rules.py -k table_row -v`
Expected: FAIL — `assert 'Medium' == 'Informational'` for `table_row_moved`, which currently falls through to `DEFAULT_RISK`.

- [ ] **Step 3: Add the risk entries**

In `backend/app/risk_rules.py`, find:

```python
    "section_heading_changed": "Medium",
```

Replace with:

```python
    "section_heading_changed": "Medium",
    "table_row_added": "Medium",
    "table_row_deleted": "Medium",
    "table_row_moved": "Informational",
```

- [ ] **Step 4: Run it to verify it passes**

Run: `cd backend && python -m pytest tests/test_risk_rules.py -q`
Expected: all pass.

- [ ] **Step 5: Write the failing row-diff tests**

Append to `backend/tests/test_table_diff.py`:

```python
from app.table_diff import diff_rows


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
```

- [ ] **Step 6: Run them to verify they fail**

Run: `cd backend && python -m pytest tests/test_table_diff.py -k row -q`
Expected: FAIL with `ImportError: cannot import name 'diff_rows'`.

- [ ] **Step 7: Implement `diff_rows`**

Add to the imports at the top of `backend/app/table_diff.py`:

```python
import uuid

from app import risk_rules
from app.models import Change, Paragraph
from app.section_structure import _longest_increasing_subsequence_indices
```

Replace the existing `from app.models import Paragraph` line with the `Change, Paragraph` import above, and append this function to the end of the file:

```python
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
```

Note the tests above unpack three values — `changes, excluded, _alignment = diff_rows(...)`. Adjust each `diff_rows` call in the tests accordingly.

- [ ] **Step 8: Run them to verify they pass**

Run: `cd backend && python -m pytest tests/test_table_diff.py -q`
Expected: all pass, including the four new row tests.

- [ ] **Step 9: Commit**

```bash
git add backend/app/table_diff.py backend/app/risk_rules.py backend/tests/test_table_diff.py backend/tests/test_risk_rules.py
git commit -m "feat: detect table rows added, deleted, and moved"
```

---

### Task 4: Detect columns added, deleted, and moved

**Files:**
- Modify: `backend/app/table_diff.py`
- Modify: `backend/app/risk_rules.py`
- Test: `backend/tests/test_table_diff.py`
- Test: `backend/tests/test_risk_rules.py`

**Interfaces:**
- Consumes: `TableGrid`, `_match_lines`, `_line_change` from Tasks 2 and 3, plus the **row alignment** returned by `diff_rows`.
- Produces: `diff_columns(old_grid: TableGrid, new_grid: TableGrid, row_alignment: list[tuple[int, int]]) -> tuple[list[Change], set[int]]`.

**The row alignment is not optional.** Columns must be compared over only the rows that matched. Comparing full columns was prototyped against the real `TableHeaderFooterDemo` pair and produced a false `table_column_deleted` + `table_column_added` pair: the newly added "Microbial Limits" row contributed text to every new column, dragging the edited `Limit` column's similarity to **0.80**, just under threshold. Restricted to matched rows it scores **0.94** and correctly stays matched.

- [ ] **Step 1: Write the failing risk test**

Append to `backend/tests/test_risk_rules.py`:

```python
def test_table_column_change_types_have_explicit_risk():
    assert assign_risk("table_column_added") == "Medium"
    assert assign_risk("table_column_deleted") == "Medium"
    assert assign_risk("table_column_moved") == "Informational"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && python -m pytest tests/test_risk_rules.py -k table_column -v`
Expected: FAIL — `table_column_moved` falls through to `DEFAULT_RISK` of `"Medium"`.

- [ ] **Step 3: Add the risk entries**

In `backend/app/risk_rules.py`, find:

```python
    "table_row_moved": "Informational",
```

Replace with:

```python
    "table_row_moved": "Informational",
    "table_column_added": "Medium",
    "table_column_deleted": "Medium",
    "table_column_moved": "Informational",
```

- [ ] **Step 4: Write the failing column tests**

Append to `backend/tests/test_table_diff.py`:

```python
from app.table_diff import diff_columns


def test_column_added_is_reported_once_with_the_whole_column():
    old_grid, new_grid = _grids(
        [cell(0, 0, 0, "Param"), cell(0, 0, 1, "Spec"),
         cell(0, 1, 0, "Assay"), cell(0, 1, 1, "95 percent")],
        [cell(0, 0, 0, "Param"), cell(0, 0, 1, "Spec"), cell(0, 0, 2, "Method"),
         cell(0, 1, 0, "Assay"), cell(0, 1, 1, "95 percent"), cell(0, 1, 2, "HPLC")],
    )

    _row_changes, _row_excluded, row_alignment = diff_rows(old_grid, new_grid)
    changes, excluded = diff_columns(old_grid, new_grid, row_alignment)

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
    changes, excluded = diff_columns(old_grid, new_grid, row_alignment)

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
    changes, excluded = diff_columns(old_grid, new_grid, row_alignment)

    moved = [c for c in changes if c.change_type == "table_column_moved"]
    assert len(moved) == 1
    assert moved[0].ai_risk_level == "Informational"
    assert excluded == set()
```

- [ ] **Step 5: Run them to verify they fail**

Run: `cd backend && python -m pytest tests/test_table_diff.py -k column -q`
Expected: FAIL with `ImportError: cannot import name 'diff_columns'`.

- [ ] **Step 6: Implement `diff_columns`**

Append to `backend/app/table_diff.py`:

```python
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
```

- [ ] **Step 7: Run them to verify they pass**

Run: `cd backend && python -m pytest tests/test_table_diff.py -q && python -m pytest tests/test_risk_rules.py -q`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add backend/app/table_diff.py backend/app/risk_rules.py backend/tests/test_table_diff.py backend/tests/test_risk_rules.py
git commit -m "feat: detect table columns added, deleted, and moved"
```

---

### Task 5: Detect merged-cell changes

**Files:**
- Modify: `backend/app/table_diff.py`
- Modify: `backend/app/risk_rules.py`
- Test: `backend/tests/test_table_diff.py`
- Test: `backend/tests/test_risk_rules.py`

**Interfaces:**
- Consumes: `TableGrid.span_at` from Task 2, `_line_change` from Task 3.
- Produces: `diff_merges(old_grid: TableGrid, new_grid: TableGrid) -> list[Change]`. Returns changes only — merge changes never suppress anything, so there is no exclusion set.

- [ ] **Step 1: Write the failing risk test**

Append to `backend/tests/test_risk_rules.py`:

```python
def test_table_cell_merge_changed_is_informational_risk():
    assert assign_risk("table_cell_merge_changed") == "Informational"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && python -m pytest tests/test_risk_rules.py -k merge -v`
Expected: FAIL — `assert 'Medium' == 'Informational'`.

- [ ] **Step 3: Add the risk entry**

In `backend/app/risk_rules.py`, find:

```python
    "table_column_moved": "Informational",
```

Replace with:

```python
    "table_column_moved": "Informational",
    "table_cell_merge_changed": "Informational",
```

- [ ] **Step 4: Write the failing merge tests**

Append to `backend/tests/test_table_diff.py`:

```python
from app.table_diff import diff_merges


def test_newly_merged_cell_is_reported():
    old_grid, new_grid = _grids(
        [cell(0, 0, 0, "Limit"), cell(0, 0, 1, "Limit")],
        [cell(0, 0, 0, "Limit", col_span=2)],
    )

    changes = diff_merges(old_grid, new_grid)

    assert len(changes) == 1
    assert changes[0].change_type == "table_cell_merge_changed"
    assert changes[0].ai_risk_level == "Informational"


def test_unmerged_cell_is_reported():
    old_grid, new_grid = _grids(
        [cell(0, 0, 0, "Limit", row_span=2)],
        [cell(0, 0, 0, "Limit"), cell(0, 1, 0, "Limit")],
    )

    changes = diff_merges(old_grid, new_grid)

    assert len(changes) == 1
    assert changes[0].change_type == "table_cell_merge_changed"


def test_unchanged_spans_report_nothing():
    old_grid, new_grid = _grids(
        [cell(0, 0, 0, "Limit", col_span=2), cell(0, 1, 0, "Assay")],
        [cell(0, 0, 0, "Limit", col_span=2), cell(0, 1, 0, "Assay")],
    )

    assert diff_merges(old_grid, new_grid) == []
```

- [ ] **Step 5: Run them to verify they fail**

Run: `cd backend && python -m pytest tests/test_table_diff.py -k merge -q`
Expected: FAIL with `ImportError: cannot import name 'diff_merges'`.

- [ ] **Step 6: Implement `diff_merges`**

Append to `backend/app/table_diff.py`:

```python
def diff_merges(old_grid: TableGrid, new_grid: TableGrid) -> list[Change]:
    # Only positions present in both grids can be compared. A position that
    # exists in one and not the other is a merge boundary shifting, which the
    # anchor's own span change already reports - counting it again here would
    # double-report one merge.
    changes: list[Change] = []
    for position in sorted(set(old_grid.cells) & set(new_grid.cells)):
        row, col = position
        old_span = old_grid.span_at(row, col)
        new_span = new_grid.span_at(row, col)
        if old_span == new_span:
            continue
        changes.append(_line_change(
            "table_cell_merge_changed",
            old_grid.text_at(row, col), new_grid.text_at(row, col),
            f"Table cell at row {row + 1}, column {col + 1} changed from spanning "
            f"{old_span[0]}x{old_span[1]} to {new_span[0]}x{new_span[1]} cells.",
        ))
    return changes
```

- [ ] **Step 7: Run them to verify they pass**

Run: `cd backend && python -m pytest tests/test_table_diff.py -q`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add backend/app/table_diff.py backend/app/risk_rules.py backend/tests/test_table_diff.py backend/tests/test_risk_rules.py
git commit -m "feat: detect table cell merge and unmerge changes"
```

---

### Task 6: Wire table structure diffing into the pipeline

**Files:**
- Modify: `backend/app/table_diff.py`
- Modify: `backend/app/pipeline.py`
- Test: `backend/tests/test_table_diff.py`
- Test: `backend/tests/test_pipeline.py`

**Interfaces:**
- Consumes: `build_grids`, `match_tables`, `diff_rows`, `diff_columns`, `diff_merges` from Tasks 2-5.
- Produces: `detect_table_structure_changes(old_paragraphs, new_paragraphs) -> tuple[list[Change], set[int]]` — the single entry point the pipeline calls.

- [ ] **Step 1: Write the failing entry-point test**

Append to `backend/tests/test_table_diff.py`:

```python
from app.table_diff import detect_table_structure_changes


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
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd backend && python -m pytest tests/test_table_diff.py -k entry_point -q`
Expected: FAIL with `ImportError: cannot import name 'detect_table_structure_changes'`.

- [ ] **Step 3: Implement the entry point**

Append to `backend/app/table_diff.py`:

```python
def detect_table_structure_changes(
    old_paragraphs: list[Paragraph], new_paragraphs: list[Paragraph]
) -> tuple[list[Change], set[int]]:
    changes: list[Change] = []
    excluded: set[int] = set()
    for old_grid, new_grid in match_tables(build_grids(old_paragraphs), build_grids(new_paragraphs)):
        row_changes, row_excluded, row_alignment = diff_rows(old_grid, new_grid)
        column_changes, column_excluded = diff_columns(old_grid, new_grid, row_alignment)
        changes.extend(row_changes)
        changes.extend(column_changes)
        changes.extend(diff_merges(old_grid, new_grid))
        excluded.update(row_excluded)
        excluded.update(column_excluded)
    return changes, excluded
```

- [ ] **Step 4: Run them to verify they pass**

Run: `cd backend && python -m pytest tests/test_table_diff.py -q`
Expected: all pass.

- [ ] **Step 5: Write the failing pipeline test**

Append to `backend/tests/test_pipeline.py`:

```python
def test_pipeline_reports_an_added_table_row_once_instead_of_per_cell(monkeypatch):
    # The whole point of the feature: one structural edit, one row in the report.
    def fail_if_called(unresolved):
        raise AssertionError("no AI call expected")

    monkeypatch.setattr(llm_classifier, "classify_changes_batch", fail_if_called)

    position = lambda r, c: TableCoordinate(table_id=0, row=r, col=c)
    old_paragraphs = [
        Paragraph(text="4.0 Procedure"),
        Paragraph(text="Parameter", from_table=True, table_position=position(0, 0)),
        Paragraph(text="Target", from_table=True, table_position=position(0, 1)),
        Paragraph(text="Compression Force", from_table=True, table_position=position(1, 0)),
        Paragraph(text="15 kN", from_table=True, table_position=position(1, 1)),
    ]
    new_paragraphs = [
        Paragraph(text="4.0 Procedure"),
        Paragraph(text="Parameter", from_table=True, table_position=position(0, 0)),
        Paragraph(text="Target", from_table=True, table_position=position(0, 1)),
        Paragraph(text="Compression Force", from_table=True, table_position=position(1, 0)),
        Paragraph(text="15 kN", from_table=True, table_position=position(1, 1)),
        Paragraph(text="Hardness", from_table=True, table_position=position(2, 0)),
        Paragraph(text="8 kg", from_table=True, table_position=position(2, 1)),
    ]

    result = pipeline.compare_documents(old_paragraphs, new_paragraphs, "old.txt", "new.txt")

    change_types = [c.change_type for c in result.changes]
    assert change_types.count("table_row_added") == 1
    # The two cells of the added row must not also be reported individually.
    assert "added_table_content" not in change_types
```

- [ ] **Step 6: Run it to verify it fails**

Run: `cd backend && python -m pytest tests/test_pipeline.py -k added_table_row_once -v`
Expected: FAIL — `assert 0 == 1`, because `pipeline.py` does not call the table diff yet, so the row reports as two `added_table_content` changes.

- [ ] **Step 7: Wire it into the pipeline**

In `backend/app/pipeline.py`, add to the imports at the top:

```python
from app import sectioning, section_matching, section_structure, paragraph_diff, move_reconciliation
from app import regex_detectors, llm_classifier, risk_rules, table_diff
```

(extend the existing second import line with `table_diff`).

Then find the start of the remaining-inserts loop:

```python
    for p, section in remaining_inserts:
        if id(p) in whole_inserted_paragraph_ids:
            continue
```

Insert the table diff immediately **above** that loop, and extend both guards:

```python
    table_structure_changes, table_structure_excluded = table_diff.detect_table_structure_changes(
        old_paragraphs, new_paragraphs
    )
    changes.extend(table_structure_changes)

    for p, section in remaining_inserts:
        if id(p) in whole_inserted_paragraph_ids or id(p) in table_structure_excluded:
            continue
```

Then find the remaining-deletes loop guard:

```python
    for p, section in remaining_deletes:
        if id(p) in whole_deleted_paragraph_ids:
            continue
```

Replace with:

```python
    for p, section in remaining_deletes:
        if id(p) in whole_deleted_paragraph_ids or id(p) in table_structure_excluded:
            continue
```

Note the table diff must be computed before both loops, since both consult its exclusion set. The deletes loop appears earlier in the function than the inserts loop, so place the two new statements above the deletes loop.

- [ ] **Step 8: Run it to verify it passes**

Run: `cd backend && python -m pytest tests/test_pipeline.py -k added_table_row_once -v`
Expected: PASS.

- [ ] **Step 9: Run the full backend suite**

Run: `cd backend && python -m pytest -q`
Expected: all pass. Pay particular attention to `test_table_row_addition_only_sets_new_table_position` and the `AllFeaturesDemo` real-document tests — a row addition that previously reported as N `added_table_content` changes now reports as one `table_row_added`, so any existing test asserting the old per-cell behaviour is a genuine expectation change and must be updated deliberately rather than worked around. If one fails, read it and decide whether the new behaviour is correct before editing.

- [ ] **Step 10: Verify against the real corpus**

Run the real DOCX pairs through the pipeline and read the output:

```bash
cd backend && python -c "
from unittest.mock import patch
from app.extraction import extract_text
from app import pipeline, llm_classifier
import glob, os
with patch.object(llm_classifier, 'classify_changes_batch', lambda u: []):
    for v1 in sorted(glob.glob('../test-documents/docx/*_v1.docx')):
        v2 = v1.replace('_v1.docx', '_v2.docx')
        if not os.path.exists(v2):
            continue
        r = pipeline.compare_documents(extract_text(v1,'docx'), extract_text(v2,'docx'), v1, v2)
        table_rows = [c for c in r.changes if c.change_type.startswith('table_')]
        if table_rows:
            print(os.path.basename(v1))
            for c in table_rows:
                print('   ', c.change_type, '|', c.reason)
" 2>&1 | grep -v "section_matching\|MATCHED\|<->\|Loading weights\|Warning:\|INSERTED\|DELETED"
```

Expected: `AllFeaturesDemo` and `RequirementsCoverageDemo` each report one `table_row_added` for the Hardness row that previously produced three `added_table_content` changes. Read every line printed and confirm each is genuinely a structural edit rather than a misclassification.

- [ ] **Step 11: Commit**

```bash
git add backend/app/table_diff.py backend/app/pipeline.py backend/tests/test_table_diff.py backend/tests/test_pipeline.py
git commit -m "feat: report table structure changes and suppress their per-cell noise"
```
