# DOCX Table Coordinates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract and retain a `TableCoordinate` (table ID, row, column) on every `Paragraph` that comes from a DOCX table cell, so a future feature can build structural table comparison on top of it. Extraction/storage only — no new comparison logic in this pass.

**Architecture:** A new `TableCoordinate` dataclass and a new `Paragraph.table_position` field in `backend/app/models.py`. `backend/app/extraction.py`'s existing table-walking code (`_iter_docx_paragraphs`) gains a shared `itertools.count()` threaded through body/header/footer extraction and through nested-table recursion, assigning each table a globally-unique sequential ID and each cell its grid row/column at first occurrence (which, verified empirically against a real merged-cell document, is always the correct top-left anchor).

**Tech Stack:** Python 3, pytest, python-docx — no new dependencies.

## Global Constraints

- New dataclass: `TableCoordinate(table_id: int, row: int, col: int)` — all three fields required, no defaults.
- New field: `Paragraph.table_position: Optional[TableCoordinate] = None`.
- `Paragraph.from_table: bool` is NOT modified, removed, or reinterpreted — it keeps its exact current meaning and behavior.
- `table_id`: a single global sequential counter (`0, 1, 2, ...`), shared across the entire document (body, every header, every footer, and nested tables), assigned the first time each table is encountered in `_extract_docx`'s existing walk order.
- `row`/`col`: 0-indexed grid position, taken at each cell's first (non-duplicate) occurrence during iteration.
- Nested tables: a paragraph's `table_position` reflects the innermost table it's directly inside (its own `table_id`/`row`/`col`), never an outer table's coordinates.
- No changes to `db.py`, `repository.py`, `export.py`, or the frontend — `table_position` is not persisted or surfaced anywhere in this pass.
- Reference: `docs/superpowers/specs/2026-08-14-docx-table-coordinates-design.md`.

---

### Task 1: Add TableCoordinate and Paragraph.table_position

**Files:**
- Modify: `backend/app/models.py`
- Modify: `backend/tests/test_models.py`

**Interfaces:**
- Produces: `TableCoordinate(table_id: int, row: int, col: int)` and `Paragraph.table_position: Optional[TableCoordinate] = None`, both in `app/models.py`. Consumed by Task 2.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_models.py` (add `TableCoordinate` to the existing import line at the top of the file, which currently reads `from app.models import (Paragraph, Section, SectionMatch, SectionMatchResult, MovedParagraph, RegexDetection, LLMClassification, Change, ComparisonSummary, ComparisonResult, build_summary,)` — insert `TableCoordinate` into that tuple):

```python
def test_paragraph_table_position_defaults_to_none():
    p = Paragraph(text="hello")
    assert p.table_position is None


def test_table_coordinate_holds_id_row_and_column():
    coord = TableCoordinate(table_id=2, row=1, col=3)
    assert coord.table_id == 2
    assert coord.row == 1
    assert coord.col == 3


def test_paragraph_can_carry_a_table_position():
    coord = TableCoordinate(table_id=0, row=0, col=0)
    p = Paragraph(text="cell text", from_table=True, table_position=coord)
    assert p.table_position is coord
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `backend/`): `python -m pytest tests/test_models.py -v`
Expected: the 3 new tests FAIL with `ImportError`/`TypeError` (`TableCoordinate` doesn't exist yet, `table_position` isn't a valid `Paragraph` keyword yet).

- [ ] **Step 3: Write the implementation**

In `backend/app/models.py`, add a new dataclass immediately before `Paragraph` (it must be defined first, since `Paragraph` references it directly as a type, not as a string forward-reference):

```python
@dataclass
class TableCoordinate:
    table_id: int
    row: int
    col: int
```

Then add the new field to `Paragraph`, immediately after the existing `from_table` field:

```python
@dataclass
class Paragraph:
    text: str
    page: Optional[int] = None
    paragraph_index: Optional[int] = None
    is_heading: bool = False
    allow_text_pattern_heading: bool = True
    from_table: bool = False
    table_position: Optional[TableCoordinate] = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_models.py -v`
Expected: PASS, all tests.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models.py backend/tests/test_models.py
git commit -m "feat: add TableCoordinate and Paragraph.table_position"
```

---

### Task 2: Extract table coordinates during DOCX extraction

**Files:**
- Modify: `backend/app/extraction.py`
- Modify: `backend/tests/test_extraction.py`

**Interfaces:**
- Consumes: `TableCoordinate`, `Paragraph.table_position` from Task 1.
- Produces: nothing new for later tasks — this is the last task in the plan. `extract_text(file_path, "docx")`'s public return type is unchanged (`list[Paragraph]`); only the returned `Paragraph` objects now have `table_position` populated for table-cell content.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_extraction.py` (uses the same `tmp_path` + `DocxDocument` fixture-building style already used throughout this file — no new imports needed, `DocxDocument` is already imported at the top):

```python
def test_extract_docx_table_cell_gets_correct_grid_coordinate(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "TopLeft"
    table.cell(0, 1).text = "TopRight"
    table.cell(1, 0).text = "BottomLeft"
    table.cell(1, 1).text = "BottomRight"
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")
    by_text = {p.text: p for p in paragraphs}

    assert by_text["TopLeft"].table_position.row == 0
    assert by_text["TopLeft"].table_position.col == 0
    assert by_text["TopRight"].table_position.row == 0
    assert by_text["TopRight"].table_position.col == 1
    assert by_text["BottomLeft"].table_position.row == 1
    assert by_text["BottomLeft"].table_position.col == 0
    assert by_text["BottomRight"].table_position.row == 1
    assert by_text["BottomRight"].table_position.col == 1
    # All four cells belong to the same (only) table in the document.
    table_ids = {p.table_position.table_id for p in by_text.values()}
    assert len(table_ids) == 1


def test_extract_docx_non_table_paragraph_has_no_table_position(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    doc.add_paragraph("1.0 Scope", style="Heading 1")
    doc.add_paragraph("This procedure applies to all lab testing.")
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")

    assert all(p.table_position is None for p in paragraphs)


def test_extract_docx_horizontally_merged_cell_anchors_at_top_left(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).merge(table.cell(0, 1))
    table.cell(0, 0).text = "MERGED HEADER CELL"
    table.cell(1, 0).text = "A"
    table.cell(1, 1).text = "B"
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")
    by_text = {p.text: p for p in paragraphs}

    assert by_text["MERGED HEADER CELL"].table_position.row == 0
    assert by_text["MERGED HEADER CELL"].table_position.col == 0
    assert by_text["A"].table_position.row == 1
    assert by_text["A"].table_position.col == 0
    assert by_text["B"].table_position.row == 1
    assert by_text["B"].table_position.col == 1


def test_extract_docx_vertically_merged_cell_anchors_at_top_left(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).merge(table.cell(1, 0))
    table.cell(0, 0).text = "VMERGED"
    table.cell(0, 1).text = "TOP RIGHT"
    table.cell(1, 1).text = "BOTTOM RIGHT"
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")
    by_text = {p.text: p for p in paragraphs}

    assert by_text["VMERGED"].table_position.row == 0
    assert by_text["VMERGED"].table_position.col == 0
    assert by_text["TOP RIGHT"].table_position.row == 0
    assert by_text["TOP RIGHT"].table_position.col == 1
    assert by_text["BOTTOM RIGHT"].table_position.row == 1
    assert by_text["BOTTOM RIGHT"].table_position.col == 1


def test_extract_docx_multiple_body_tables_get_distinct_sequential_ids(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    first_table = doc.add_table(rows=1, cols=1)
    first_table.cell(0, 0).text = "First Table Cell"
    doc.add_paragraph("Some text between the two tables.")
    second_table = doc.add_table(rows=1, cols=1)
    second_table.cell(0, 0).text = "Second Table Cell"
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")
    by_text = {p.text: p for p in paragraphs}

    first_id = by_text["First Table Cell"].table_position.table_id
    second_id = by_text["Second Table Cell"].table_position.table_id
    assert first_id != second_id
    assert second_id > first_id


def test_extract_docx_body_and_header_tables_share_the_global_id_counter(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    body_table = doc.add_table(rows=1, cols=1)
    body_table.cell(0, 0).text = "Body Table Cell"
    doc.add_paragraph("Body content here.")
    header = doc.sections[0].header
    header.paragraphs[0].text = "SOP-1234"
    header_table = header.add_table(rows=1, cols=1, width=Inches(6))
    header_table.cell(0, 0).text = "Header Table Cell"
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")
    by_text = {p.text: p for p in paragraphs}

    body_id = by_text["Body Table Cell"].table_position.table_id
    header_id = by_text["Header Table Cell"].table_position.table_id
    assert body_id != header_id


def test_extract_docx_nested_table_gets_its_own_table_id_and_coordinates(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    outer_table = doc.add_table(rows=1, cols=2)
    outer_table.cell(0, 0).text = "Outer Cell"
    nested_table = outer_table.cell(0, 1).add_table(rows=1, cols=1)
    nested_table.cell(0, 0).text = "Nested Cell"
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")
    by_text = {p.text: p for p in paragraphs}

    outer_position = by_text["Outer Cell"].table_position
    nested_position = by_text["Nested Cell"].table_position

    assert outer_position.table_id != nested_position.table_id
    # The nested table's own single cell is at its own grid position (0, 0),
    # not the outer cell's position (0, 1) that contains it.
    assert nested_position.row == 0
    assert nested_position.col == 0
    assert outer_position.row == 0
    assert outer_position.col == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_extraction.py -v`
Expected: the 7 new tests FAIL — either with an `AttributeError` (`table_position` is `None` where a coordinate is expected, since `_iter_docx_paragraphs` doesn't populate it yet) or, if the current 3-element-tuple unpacking in `_extract_docx` doesn't match what the new tests exercise, some may error rather than fail cleanly. Either way, all 7 must NOT pass yet. Every pre-existing test in the file must still PASS unchanged (nothing about today's public behavior is different yet).

- [ ] **Step 3: Add the `itertools` import**

At the top of `backend/app/extraction.py`, add:

```python
import itertools
```

(alongside the existing `import collections` line — the file currently starts with `import collections`, then `import fitz`, etc.; add the new import in the same block, before `import fitz`.)

- [ ] **Step 4: Change `_iter_docx_paragraphs`'s signature and yield shape**

Find the current function (verify by reading the file first — this may have drifted):

```python
def _iter_docx_paragraphs(content_iter, allow_text_pattern_heading=True):
    for item in content_iter:
        if isinstance(item, DocxParagraph):
            yield item, allow_text_pattern_heading, False
        elif isinstance(item, DocxTable):
            seen_cells = set()
            for row in item.rows:
                for cell in row.cells:
                    # python-docx's row.cells returns one proxy per grid column, so a
                    # horizontally merged cell is returned once per spanned column, and a
                    # vertically merged cell reappears in every spanned row - all of these
                    # proxies wrap the same underlying <w:tc> element. python-docx exposes
                    # no public identity check for "this proxy wraps a cell I already
                    # visited", so we dedupe on the underlying XML element itself (`_tc`).
                    # Note: we must keep the element object itself in the set (not e.g.
                    # id(cell._tc)) - lxml only guarantees a stable id() for an element
                    # while some Python reference to its proxy is still alive; for a
                    # vertical merge, row.cells re-derives the continuation cell's `_tc`
                    # via a fresh lookup (tc_above) each time, so if we didn't hold a
                    # live reference here, the earlier proxy could be garbage collected
                    # and id() would no longer match on the next row.
                    if cell._tc in seen_cells:
                        continue
                    seen_cells.add(cell._tc)
                    # Once inside any table, text-pattern heading detection (ALL-CAPS,
                    # numbered) is unreliable - table cells are full of short uppercase
                    # abbreviations (HPLC, NMT 0.5%) that look exactly like a heading by
                    # shape alone. Structural signals (Word style, font-size) still work
                    # fine inside a cell, so only the text-pattern fallback is disabled.
                    # from_table is always True here regardless of what was passed in -
                    # once inside a table, it stays True even for a table nested inside
                    # a header/footer, or a table nested inside another table's cell.
                    for para, _, _ in _iter_docx_paragraphs(cell.iter_inner_content(), allow_text_pattern_heading=False):
                        yield para, False, True
```

Replace it with:

```python
def _iter_docx_paragraphs(content_iter, allow_text_pattern_heading=True, table_id_counter=None):
    if table_id_counter is None:
        table_id_counter = itertools.count()
    for item in content_iter:
        if isinstance(item, DocxParagraph):
            yield item, allow_text_pattern_heading, False, None
        elif isinstance(item, DocxTable):
            table_id = next(table_id_counter)
            seen_cells = set()
            for row_index, row in enumerate(item.rows):
                for col_index, cell in enumerate(row.cells):
                    # python-docx's row.cells returns one proxy per grid column, so a
                    # horizontally merged cell is returned once per spanned column, and a
                    # vertically merged cell reappears in every spanned row - all of these
                    # proxies wrap the same underlying <w:tc> element. python-docx exposes
                    # no public identity check for "this proxy wraps a cell I already
                    # visited", so we dedupe on the underlying XML element itself (`_tc`).
                    # Note: we must keep the element object itself in the set (not e.g.
                    # id(cell._tc)) - lxml only guarantees a stable id() for an element
                    # while some Python reference to its proxy is still alive; for a
                    # vertical merge, row.cells re-derives the continuation cell's `_tc`
                    # via a fresh lookup (tc_above) each time, so if we didn't hold a
                    # live reference here, the earlier proxy could be garbage collected
                    # and id() would no longer match on the next row.
                    if cell._tc in seen_cells:
                        continue
                    seen_cells.add(cell._tc)
                    # Once inside any table, text-pattern heading detection (ALL-CAPS,
                    # numbered) is unreliable - table cells are full of short uppercase
                    # abbreviations (HPLC, NMT 0.5%) that look exactly like a heading by
                    # shape alone. Structural signals (Word style, font-size) still work
                    # fine inside a cell, so only the text-pattern fallback is disabled.
                    # from_table is always True here regardless of what was passed in -
                    # once inside a table, it stays True even for a table nested inside
                    # a header/footer, or a table nested inside another table's cell.
                    #
                    # The row/col index here is captured at each cell's first (non-duplicate)
                    # occurrence, which is always the top-left anchor for a merged cell -
                    # verified empirically against real horizontal and vertical merges before
                    # writing this. This is the same fact the dedup above already relies on,
                    # just also read as the cell's grid coordinate.
                    position = TableCoordinate(table_id=table_id, row=row_index, col=col_index)
                    for para, _, _, inner_position in _iter_docx_paragraphs(
                        cell.iter_inner_content(),
                        allow_text_pattern_heading=False,
                        table_id_counter=table_id_counter,
                    ):
                        # A paragraph from a table nested even deeper than this cell already
                        # carries its own (innermost) table's coordinate - preserve that
                        # instead of overwriting it with this cell's position.
                        yield para, False, True, inner_position if inner_position is not None else position
```

- [ ] **Step 5: Add `TableCoordinate` to this file's imports**

At the top of `backend/app/extraction.py`, find:

```python
from app.models import Paragraph
```

Replace with:

```python
from app.models import Paragraph, TableCoordinate
```

- [ ] **Step 6: Add `table_position` to `_docx_paragraph_to_model`**

Find the current function:

```python
def _docx_paragraph_to_model(
    para, index: int, baseline_pt: float, allow_text_pattern_heading: bool = True, from_table: bool = False
) -> Paragraph | None:
    text = para.text.strip()
    if not text:
        return None
    style_name = para.style.name if para.style else ""
    is_heading_style = style_name.startswith(HEADING_STYLE_PREFIXES)

    size_pt = _docx_paragraph_font_size_pt(para)
    is_heading_size = (
        size_pt is not None
        and size_pt >= baseline_pt + DOCX_HEADING_SIZE_DELTA_PT
        and _looks_like_heading_shape(text)
    )

    return Paragraph(
        text=text,
        paragraph_index=index,
        is_heading=is_heading_style or is_heading_size,
        allow_text_pattern_heading=allow_text_pattern_heading,
        from_table=from_table,
    )
```

Replace with:

```python
def _docx_paragraph_to_model(
    para, index: int, baseline_pt: float, allow_text_pattern_heading: bool = True, from_table: bool = False,
    table_position: TableCoordinate | None = None,
) -> Paragraph | None:
    text = para.text.strip()
    if not text:
        return None
    style_name = para.style.name if para.style else ""
    is_heading_style = style_name.startswith(HEADING_STYLE_PREFIXES)

    size_pt = _docx_paragraph_font_size_pt(para)
    is_heading_size = (
        size_pt is not None
        and size_pt >= baseline_pt + DOCX_HEADING_SIZE_DELTA_PT
        and _looks_like_heading_shape(text)
    )

    return Paragraph(
        text=text,
        paragraph_index=index,
        is_heading=is_heading_style or is_heading_size,
        allow_text_pattern_heading=allow_text_pattern_heading,
        from_table=from_table,
        table_position=table_position,
    )
```

- [ ] **Step 7: Thread the shared counter through `_extract_docx`**

Find the current function:

```python
def _extract_docx(file_path: str) -> list[Paragraph]:
    doc = DocxDocument(file_path)
    baseline_pt = _docx_body_baseline_pt(doc)

    paragraphs: list[Paragraph] = []
    index = 0
    for para, allow_text_pattern_heading, from_table in _iter_docx_paragraphs(doc.iter_inner_content()):
        model = _docx_paragraph_to_model(para, index, baseline_pt, allow_text_pattern_heading, from_table)
        if model is not None:
            paragraphs.append(model)
            index += 1

    header_paragraphs = []
    footer_paragraphs = []
    for section in doc.sections:
        if not section.header.is_linked_to_previous:
            header_paragraphs.extend(
                _iter_docx_paragraphs(section.header.iter_inner_content(), allow_text_pattern_heading=False)
            )
        if not section.footer.is_linked_to_previous:
            footer_paragraphs.extend(
                _iter_docx_paragraphs(section.footer.iter_inner_content(), allow_text_pattern_heading=False)
            )

    # Filter out paragraphs with no real text (whitespace-only, or image/drawing-only
    # content where python-docx's Paragraph.text is empty) before checking emptiness,
    # so a header/footer with no actual content doesn't emit a bare pseudo-section.
    header_paragraphs = [(p, atph, ft) for p, atph, ft in header_paragraphs if p.text.strip()]
    footer_paragraphs = [(p, atph, ft) for p, atph, ft in footer_paragraphs if p.text.strip()]

    if header_paragraphs:
        paragraphs.append(Paragraph(text="Page Header", paragraph_index=index, is_heading=True))
        index += 1
        for para, allow_text_pattern_heading, from_table in header_paragraphs:
            model = _docx_paragraph_to_model(para, index, baseline_pt, allow_text_pattern_heading, from_table)
            if model is not None:
                paragraphs.append(model)
                index += 1

    if footer_paragraphs:
        paragraphs.append(Paragraph(text="Page Footer", paragraph_index=index, is_heading=True))
        index += 1
        for para, allow_text_pattern_heading, from_table in footer_paragraphs:
            model = _docx_paragraph_to_model(para, index, baseline_pt, allow_text_pattern_heading, from_table)
            if model is not None:
                paragraphs.append(model)
                index += 1

    return paragraphs
```

Replace it with:

```python
def _extract_docx(file_path: str) -> list[Paragraph]:
    doc = DocxDocument(file_path)
    baseline_pt = _docx_body_baseline_pt(doc)
    table_id_counter = itertools.count()

    paragraphs: list[Paragraph] = []
    index = 0
    for para, allow_text_pattern_heading, from_table, table_position in _iter_docx_paragraphs(
        doc.iter_inner_content(), table_id_counter=table_id_counter
    ):
        model = _docx_paragraph_to_model(
            para, index, baseline_pt, allow_text_pattern_heading, from_table, table_position
        )
        if model is not None:
            paragraphs.append(model)
            index += 1

    header_paragraphs = []
    footer_paragraphs = []
    for section in doc.sections:
        if not section.header.is_linked_to_previous:
            header_paragraphs.extend(
                _iter_docx_paragraphs(
                    section.header.iter_inner_content(),
                    allow_text_pattern_heading=False,
                    table_id_counter=table_id_counter,
                )
            )
        if not section.footer.is_linked_to_previous:
            footer_paragraphs.extend(
                _iter_docx_paragraphs(
                    section.footer.iter_inner_content(),
                    allow_text_pattern_heading=False,
                    table_id_counter=table_id_counter,
                )
            )

    # Filter out paragraphs with no real text (whitespace-only, or image/drawing-only
    # content where python-docx's Paragraph.text is empty) before checking emptiness,
    # so a header/footer with no actual content doesn't emit a bare pseudo-section.
    header_paragraphs = [
        (p, atph, ft, tp) for p, atph, ft, tp in header_paragraphs if p.text.strip()
    ]
    footer_paragraphs = [
        (p, atph, ft, tp) for p, atph, ft, tp in footer_paragraphs if p.text.strip()
    ]

    if header_paragraphs:
        paragraphs.append(Paragraph(text="Page Header", paragraph_index=index, is_heading=True))
        index += 1
        for para, allow_text_pattern_heading, from_table, table_position in header_paragraphs:
            model = _docx_paragraph_to_model(
                para, index, baseline_pt, allow_text_pattern_heading, from_table, table_position
            )
            if model is not None:
                paragraphs.append(model)
                index += 1

    if footer_paragraphs:
        paragraphs.append(Paragraph(text="Page Footer", paragraph_index=index, is_heading=True))
        index += 1
        for para, allow_text_pattern_heading, from_table, table_position in footer_paragraphs:
            model = _docx_paragraph_to_model(
                para, index, baseline_pt, allow_text_pattern_heading, from_table, table_position
            )
            if model is not None:
                paragraphs.append(model)
                index += 1

    return paragraphs
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `python -m pytest tests/test_extraction.py -v`
Expected: PASS, all tests — the 7 new ones from Step 1, and every pre-existing test in the file (in particular every test involving `from_table`, merged cells, nested tables, and headers/footers — none of their assertions change, since `table_position` is additive and none of them inspect it).

- [ ] **Step 9: Run the full backend suite**

Run (from `backend/`): `python -m pytest -v`
Expected: PASS, all tests, no regressions anywhere else in the suite (nothing downstream of extraction reads `table_position` yet, so nothing else should be able to break).

- [ ] **Step 10: Manually verify against the real `TableHeaderFooterDemo_v1.docx` fixture**

This repo's existing extraction tests all build synthetic fixtures inline with python-docx rather than referencing the real files in `test-documents/docx/` — this step follows that same convention by NOT adding a new automated test against the real file, but still verifies the real-file behavior directly, matching how every other feature on this branch was checked against real fixtures before being called done. From `backend/`, run:

```python
python -c "
from app.extraction import extract_text
paragraphs = extract_text('../test-documents/docx/TableHeaderFooterDemo_v1.docx', 'docx')
for p in paragraphs:
    if p.table_position is not None:
        print(p.table_position.table_id, p.table_position.row, p.table_position.col, repr(p.text))
"
```

Expected: one line per table-cell paragraph in that file's table (it has a 4-row × 3-column `Parameter | Limit | Method` table), with `table_id` the same integer for every row (only one table in that document), and `row`/`col` matching each cell's actual position (header row cells at `row=0`, `Assay` row cells at `row=1`, etc.). Include this output in your report — it's the concrete proof this works against a real document, not just synthetic test objects.

- [ ] **Step 11: Commit**

```bash
git add backend/app/extraction.py backend/tests/test_extraction.py
git commit -m "feat: extract table_id/row/col coordinates for DOCX table cells"
```
