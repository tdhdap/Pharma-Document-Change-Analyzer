# DOCX Table Coordinates — Design

**Status:** Approved for implementation

## Purpose

Table cell content is currently extracted with only a flat `from_table: bool`
flag (`backend/app/models.py`, `Paragraph.from_table`) — there is no record
of *which* table a paragraph came from, or *where* in that table (which row,
which column). This makes any future structural table comparison (e.g.
detecting an inserted/deleted row, a moved cell) impossible, since there's
no way to correlate a cell's position between the old and new document
versions.

This is **extraction/storage only** — it adds the coordinate data during
DOCX extraction so a later feature can build comparison logic on top of it.
No new `Change` type or detection logic is added in this pass.

## Decision

Add a new dataclass and one new `Paragraph` field:

```python
@dataclass
class TableCoordinate:
    table_id: int
    row: int
    col: int
```

```python
@dataclass
class Paragraph:
    ...  # existing fields unchanged
    table_position: Optional["TableCoordinate"] = None
```

`from_table: bool` is **not** touched or replaced — it's used throughout
`pipeline.py`, `section_structure.py`, and many already-shipped tests;
removing or changing its meaning would touch a lot of reviewed code for no
benefit. `table_position` is purely additive: `None` for every paragraph
that isn't table content (unchanged from today's behavior, since the field
simply doesn't get set), and populated only for paragraphs extracted from
inside a DOCX table.

**`table_id` — no native OOXML identifier exists for a table**, so this is
synthesized: a single global sequential counter (`0, 1, 2, ...`), assigned
the first time each table is encountered during extraction, in document
order. "Document order" here means: every table in the main body first (in
the order `iter_inner_content()` walks them), then every table in each
section's header/footer (in the order `doc.sections` and the existing
header/footer loop already walks them) — this is the same order
`_extract_docx` already processes these locations in, so no new ordering
concept is introduced, just a shared counter threaded through the existing
walk. **This means a header table can get a numerically later `table_id`
than a body table that appears later on the physical page** — an accepted
consequence of reusing the existing extraction order rather than inventing
a page-position-aware one, not a defect.

**`row`/`col` are 0-indexed grid positions**, anchored at each cell's first
occurrence during iteration. Verified empirically against a real merged-cell
DOCX (both a horizontal merge and a vertical merge) before writing this
spec: `row.cells` already returns one proxy per spanned grid column/row (the
same fact the existing merged-cell dedup logic already relies on), so the
position at first encounter is always the correct top-left anchor — no
additional merge-span math is needed beyond what `_iter_docx_paragraphs`
already does.

**Nested tables** (a table inside another table's cell): a paragraph's
`table_position` reflects the **innermost** table it's directly inside — its
own `table_id`/`row`/`col` — never the outer table's coordinates. This
mirrors the existing `from_table` flag's behavior of not distinguishing
nesting depth (that boolean is `True` regardless of how deep the nesting
is), while giving `table_position` the more precise "which specific table"
answer that `from_table` alone can't express.

## Design per component

### `backend/app/models.py`

Add `TableCoordinate` (new dataclass, 3 required int fields, no defaults —
it's only ever constructed with all three values known). Add
`Paragraph.table_position: Optional[TableCoordinate] = None`.

### `backend/app/extraction.py`

**`_iter_docx_paragraphs` signature and yield shape change:**

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
                    if cell._tc in seen_cells:
                        continue
                    seen_cells.add(cell._tc)
                    position = TableCoordinate(table_id=table_id, row=row_index, col=col_index)
                    for para, _, _, inner_position in _iter_docx_paragraphs(
                        cell.iter_inner_content(),
                        allow_text_pattern_heading=False,
                        table_id_counter=table_id_counter,
                    ):
                        yield para, False, True, inner_position if inner_position is not None else position
```

Yielded tuples grow from 3 elements (`para, allow_text_pattern_heading,
from_table`) to 4 (`para, allow_text_pattern_heading, from_table,
table_position`). `table_id_counter` defaults to a fresh `itertools.count()`
when not passed, so existing standalone calls (e.g. any future unit test
constructing paragraphs directly) don't need to know about it — only
`_extract_docx` needs to thread an explicit shared one.

The recursive call's own `inner_position` is preserved when non-`None`
(that paragraph came from an even-more-deeply-nested table) — the current
cell's `position` is only substituted when the recursive call yields `None`
(meaning that paragraph is directly in this cell, not from further
nesting). This is what implements "innermost table wins" for arbitrary
nesting depth.

**`_docx_paragraph_to_model` gains a parameter:**

```python
def _docx_paragraph_to_model(
    para, index: int, baseline_pt: float, allow_text_pattern_heading: bool = True,
    from_table: bool = False, table_position: TableCoordinate | None = None,
) -> Paragraph | None:
    ...
    return Paragraph(
        text=text, paragraph_index=index,
        is_heading=is_heading_style or is_heading_size,
        allow_text_pattern_heading=allow_text_pattern_heading,
        from_table=from_table, table_position=table_position,
    )
```

**`_extract_docx` threads one shared counter through all three call sites:**

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

    header_paragraphs = [
        (p, atph, ft, tp) for p, atph, ft, tp in header_paragraphs if p.text.strip()
    ]
    footer_paragraphs = [
        (p, atph, ft, tp) for p, atph, ft, tp in footer_paragraphs if p.text.strip()
    ]
    # ... (the two subsequent append loops similarly gain table_position in
    # their unpacking and pass it through to _docx_paragraph_to_model,
    # otherwise unchanged from the current code)
```

Add `import itertools` at the top of the file.

### Unaffected

`sectioning.py`, `section_matching.py`, `section_structure.py`,
`pipeline.py`, `move_reconciliation.py`, `paragraph_diff.py`, `regex_detectors.py`,
`risk_rules.py` — no changes; nothing reads `table_position` yet. `_extract_pdf`,
`_extract_txt` — no table concept in either format, untouched. `db.py`,
`repository.py`, `export.py`, frontend — no changes; `table_position` isn't
persisted or surfaced anywhere in this pass, it exists only on the
in-memory `Paragraph` objects produced by extraction, consumed by nothing
downstream yet.

## Testing

- A simple table with no merges (e.g. 2×2) → every cell's paragraph gets
  the correct `TableCoordinate(table_id, row, col)` matching its actual
  grid position.
- A table with a horizontal merge and a table with a vertical merge (built
  directly with python-docx, mirroring the empirical check done during
  design) → the merged cell's paragraph gets exactly one `TableCoordinate`,
  anchored at the top-left position, with no duplicate yielded for the
  spanned positions (this is the existing dedup behavior, now also
  verified to produce the correct anchor coordinate, not just avoid
  duplication).
- Multiple tables in the document body → sequential, distinct `table_id`
  values in document order.
- A table in the body and a table in a header → both get valid, distinct
  `table_id` values from the same shared counter (confirming the counter
  is genuinely threaded across all three `_extract_docx` call sites, not
  reset per location).
- A table nested inside another table's cell → the nested table's
  paragraphs get their own `table_id` (different from the outer table's)
  and `row`/`col` scoped to the nested table's own grid — NOT the outer
  cell's coordinate. Outer-table paragraphs (not inside the nested table)
  keep the outer table's coordinate. This is the core correctness property
  of the nested-table design decision.
- A plain paragraph (not in any table) → `table_position is None`,
  unchanged from today.
- A real DOCX fixture already in this repo with a table
  (`test-documents/docx/TableHeaderFooterDemo_v1.docx`, which has a 4-row ×
  3-column table) → run real extraction and confirm every table-cell
  paragraph gets a sensible, correct coordinate, not just synthetic
  in-memory `Section`/`Paragraph` objects.
- Full backend suite re-run — in particular every existing test that
  constructs a `Paragraph` with `from_table=True` directly (bypassing
  extraction) must still work unchanged, since `table_position` defaults to
  `None` and nothing currently reads it.

## Out of Scope

- Any new `Change` type or comparison logic using `table_position` — this
  is a separate, not-yet-designed future feature, per your explicit choice
  to keep this pass extraction-only.
- Persisting `table_position` to the database, exporting it via
  `export.py`, or surfacing it in the frontend — nothing downstream
  consumes it yet, so there's nothing to persist or display.
- PDF/TXT table coordinate extraction — neither format has an equivalent
  structural table concept accessible the way DOCX's OOXML table model
  does.
- A page-position-aware table ordering (so header tables always sort
  before the body tables they visually precede) — the accepted ordering is
  whatever `_extract_docx`'s existing walk order already produces.
