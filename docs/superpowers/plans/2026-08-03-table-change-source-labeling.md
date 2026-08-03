# Table Change Source Labeling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every reported change carries a visible `source` ("Table" or "Body"), and the three generic structural change types (added/deleted/moved paragraph) get table-aware wording when the source is a table — so a reviewer can immediately tell "this is a new table row" from "this is a new sentence," instead of both looking identical today.

**Architecture:** A new `Paragraph.from_table` flag (set during DOCX extraction, mirroring the existing `allow_text_pattern_heading` mechanism) flows into a new `Change.source` field computed in `pipeline.py`. Only the three generic fallback change types get their wording rewritten when source is a table; every precise type (numeric/unit/date/AI-classified) is untouched. The field is persisted to SQLite and surfaced through the API/export/frontend.

**Tech Stack:** Existing backend/frontend only — `backend/app/models.py`, `extraction.py`, `pipeline.py`, `db.py`, `repository.py`, `export.py`, `frontend/pages/2_Detailed_Changes.py`. No new dependencies.

## Global Constraints

- `Paragraph.from_table: bool = False` — additive field, independent of the existing `allow_text_pattern_heading` field (not derived from it, to avoid touching the already-shipped heading-fix logic).
- `Change.source: str = "Body"` — additive field, values are exactly the strings `"Table"` and `"Body"` (no other values).
- Only these three change types get wording rewritten when source is `"Table"`: `added_paragraph` → `added_table_content` ("New table content added."), `deleted_paragraph` → `deleted_table_content` ("Table content removed."), `moved_paragraph` → `moved_table_content` ("Table content moved from '{old_section}' to '{new_section}'."). Every other change type (`numeric_change`, `unit_change`, `date_change`, and the 6 AI-classified semantic types) is never rewritten, regardless of source — only `source` is set on those, `change_type`/`reason` stay exactly as today.
- Risk classification is unchanged — the new type strings are NOT added to `risk_rules.RISK_TABLE`; they fall through to the existing `DEFAULT_RISK = "Medium"`, identical to what `added_paragraph`/`deleted_paragraph`/`moved_paragraph` already get today. Do not modify `risk_rules.py`.
- DOCX-only for `from_table` detection — `_extract_pdf`/`_extract_txt` are untouched, always leaving `from_table` at its default `False`.
- A real, already-in-use SQLite database file exists at `backend/app.db` today, predating this feature — its `changes` table has no `source` column. `CREATE TABLE IF NOT EXISTS` does not alter an existing table, so simply adding the column to the schema string is not sufficient on its own; an explicit, idempotent migration step is required so existing installations don't break the next time a comparison is saved.
- `sectioning.py`, `section_matching.py`, `paragraph_diff.py`, `move_reconciliation.py`, `regex_detectors.py`, `llm_classifier.py`, `risk_rules.py`, `frontend/pages/1_Change_Summary.py`, `frontend/pages/3_Review_and_Export.py`, `frontend/logic.py`, `frontend/api_client.py` must not change — confirmed during planning that none of them need any change for this feature.

---

### Task 1: Add `from_table`/`source` fields and wire DOCX extraction

**Files:**
- Modify: `backend/app/models.py`
- Modify: `backend/app/extraction.py`
- Test: `backend/tests/test_extraction.py`

**Interfaces:**
- Consumes: nothing new — reuses the existing `_iter_docx_paragraphs`/`_docx_paragraph_to_model`/`_extract_docx` functions from earlier plans.
- Produces: `Paragraph.from_table: bool = False` and `Change.source: str = "Body"` (new dataclass fields). Task 2 and Task 3 construct/read these by these exact names.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_extraction.py`:

```python
def test_extract_docx_table_cell_has_from_table_true(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    doc.add_paragraph("2.0 Acceptance Criteria", style="Heading 1")
    table = doc.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Method"
    table.cell(0, 1).text = "HPLC"
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")
    by_text = {p.text: p for p in paragraphs}

    assert by_text["2.0 Acceptance Criteria"].from_table is False
    assert by_text["Method"].from_table is True
    assert by_text["HPLC"].from_table is True


def test_extract_docx_body_paragraph_has_from_table_false(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    doc.add_paragraph("1.0 Scope", style="Heading 1")
    doc.add_paragraph("This procedure applies to all lab testing.")
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")

    assert all(p.from_table is False for p in paragraphs)


def test_extract_docx_header_paragraph_not_from_table(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    doc.add_paragraph("Body content here.")
    doc.sections[0].header.paragraphs[0].text = "Confidential"
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")
    header_para = next(p for p in paragraphs if p.text == "Confidential")

    assert header_para.from_table is False


def test_extract_docx_table_inside_header_has_from_table_true(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    doc.add_paragraph("Body content here.")
    header = doc.sections[0].header
    header.paragraphs[0].text = "SOP-1234"
    table = header.add_table(rows=1, cols=1)
    table.cell(0, 0).text = "Header Table Cell"
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")
    cell_para = next(p for p in paragraphs if p.text == "Header Table Cell")

    assert cell_para.from_table is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `backend/`): `pytest tests/test_extraction.py -v -k "from_table"`
Expected: FAIL — `Paragraph` has no `from_table` field yet.

- [ ] **Step 3: Add the new fields**

In `backend/app/models.py`, find:

```python
@dataclass
class Paragraph:
    text: str
    page: Optional[int] = None
    paragraph_index: Optional[int] = None
    is_heading: bool = False
    allow_text_pattern_heading: bool = True
```

Replace with:

```python
@dataclass
class Paragraph:
    text: str
    page: Optional[int] = None
    paragraph_index: Optional[int] = None
    is_heading: bool = False
    allow_text_pattern_heading: bool = True
    from_table: bool = False
```

In the same file, find:

```python
@dataclass
class Change:
    change_id: str
    section: str
    change_type: str
    old_text: str
    new_text: str
    old_page: Optional[int]
    new_page: Optional[int]
    confidence: float
    ai_risk_level: str
    reason: str
    reviewer_risk_level: Optional[str] = None
    reviewer_comment: Optional[str] = None
    accepted: bool = False
```

Replace with:

```python
@dataclass
class Change:
    change_id: str
    section: str
    change_type: str
    old_text: str
    new_text: str
    old_page: Optional[int]
    new_page: Optional[int]
    confidence: float
    ai_risk_level: str
    reason: str
    reviewer_risk_level: Optional[str] = None
    reviewer_comment: Optional[str] = None
    accepted: bool = False
    source: str = "Body"
```

- [ ] **Step 4: Thread `from_table` through `_iter_docx_paragraphs`/`_docx_paragraph_to_model`**

In `backend/app/extraction.py`, find `_iter_docx_paragraphs`:

```python
def _iter_docx_paragraphs(content_iter, allow_text_pattern_heading=True):
    for item in content_iter:
        if isinstance(item, DocxParagraph):
            yield item, allow_text_pattern_heading
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
                    yield from _iter_docx_paragraphs(cell.iter_inner_content(), allow_text_pattern_heading=False)
```

Replace with:

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

Find `_docx_paragraph_to_model`:

```python
def _docx_paragraph_to_model(para, index: int, baseline_pt: float, allow_text_pattern_heading: bool = True) -> Paragraph | None:
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
    )
```

Replace with:

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

- [ ] **Step 5: Update `_extract_docx`'s three call sites to unpack and pass through the third tuple element**

In `backend/app/extraction.py`, find `_extract_docx` and update each of its three loops that unpack `_iter_docx_paragraphs`'s output. Find:

```python
    paragraphs: list[Paragraph] = []
    index = 0
    for para, allow_text_pattern_heading in _iter_docx_paragraphs(doc.iter_inner_content()):
        model = _docx_paragraph_to_model(para, index, baseline_pt, allow_text_pattern_heading)
        if model is not None:
            paragraphs.append(model)
            index += 1
```

Replace with:

```python
    paragraphs: list[Paragraph] = []
    index = 0
    for para, allow_text_pattern_heading, from_table in _iter_docx_paragraphs(doc.iter_inner_content()):
        model = _docx_paragraph_to_model(para, index, baseline_pt, allow_text_pattern_heading, from_table)
        if model is not None:
            paragraphs.append(model)
            index += 1
```

Find the header/footer collection loop:

```python
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
    header_paragraphs = [(p, atph) for p, atph in header_paragraphs if p.text.strip()]
    footer_paragraphs = [(p, atph) for p, atph in footer_paragraphs if p.text.strip()]

    if header_paragraphs:
        paragraphs.append(Paragraph(text="Page Header", paragraph_index=index, is_heading=True))
        index += 1
        for para, allow_text_pattern_heading in header_paragraphs:
            model = _docx_paragraph_to_model(para, index, baseline_pt, allow_text_pattern_heading)
            if model is not None:
                paragraphs.append(model)
                index += 1

    if footer_paragraphs:
        paragraphs.append(Paragraph(text="Page Footer", paragraph_index=index, is_heading=True))
        index += 1
        for para, allow_text_pattern_heading in footer_paragraphs:
            model = _docx_paragraph_to_model(para, index, baseline_pt, allow_text_pattern_heading)
            if model is not None:
                paragraphs.append(model)
                index += 1

    return paragraphs
```

Replace with:

```python
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

- [ ] **Step 6: Run the new tests, then the full backend suite**

Run: `pytest tests/test_extraction.py -v`
Expected: PASS — all pre-existing tests (every test from the two prior plans on this file must still pass unmodified — merged-cell dedup, empty-header suppression, ALL-CAPS-in-table-not-a-heading, etc.) plus the 4 new ones.

Run (from `backend/`): `pytest -v`
Expected: PASS — full backend suite, no regressions.

- [ ] **Step 7: Commit**

```bash
git add backend/app/models.py backend/app/extraction.py backend/tests/test_extraction.py
git commit -m "feat: add Paragraph.from_table and Change.source fields, wire DOCX extraction"
```

---

### Task 2: Persist `source` in SQLite, with a migration for the existing database

**Files:**
- Modify: `backend/app/db.py`
- Modify: `backend/app/repository.py`
- Test: `backend/tests/test_repository.py`

**Interfaces:**
- Consumes: `Change.source` from Task 1.
- Produces: `_ensure_changes_source_column(conn: sqlite3.Connection) -> None` in `db.py` — a private migration helper, not consumed elsewhere, but named here so its existence and purpose are on record.

**Why this task matters — read before starting:** a real, already-in-use SQLite file exists at `backend/app.db` today (confirmed during planning: it has a `changes` table with no `source` column, and was last modified today). `CREATE TABLE IF NOT EXISTS` is a no-op on a table that already exists — it does **not** add new columns to it. Without an explicit migration step, the next time anyone runs a comparison against this existing database, `save_comparison`'s `INSERT` (once it includes the new `source` column) would fail outright with "table changes has no column named source". This task must not skip the migration step.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_repository.py` (add `import sqlite3` at the top of the file alongside the existing imports):

```python
def test_save_and_get_comparison_round_trip_preserves_source():
    conn = make_conn()
    old_id = repository.create_document(conn, "old.txt", "txt", "/data/old.txt")
    new_id = repository.create_document(conn, "new.txt", "txt", "/data/new.txt")

    changes = [
        Change(
            change_id="ch-1", section="2.0 Acceptance Criteria", change_type="added_table_content",
            old_text="", new_text="Microbial Limits", old_page=None, new_page=1,
            confidence=1.0, ai_risk_level="Medium", reason="New table content added.",
            source="Table",
        ),
    ]
    comparison = ComparisonResult(
        comparison_id="cmp-2", old_document="old.txt", new_document="new.txt",
        summary=build_summary(changes), changes=changes,
    )

    repository.save_comparison(conn, comparison, old_id, new_id)
    fetched = repository.get_comparison(conn, "cmp-2")

    assert fetched.changes[0].source == "Table"


def test_save_and_get_comparison_defaults_source_to_body():
    conn = make_conn()
    old_id = repository.create_document(conn, "old.txt", "txt", "/data/old.txt")
    new_id = repository.create_document(conn, "new.txt", "txt", "/data/new.txt")

    changes = [
        Change(
            change_id="ch-1", section="1.0 Scope", change_type="numeric_change",
            old_text="95%", new_text="98%", old_page=1, new_page=1,
            confidence=1.0, ai_risk_level="High", reason="value changed",
        ),
    ]
    comparison = ComparisonResult(
        comparison_id="cmp-3", old_document="old.txt", new_document="new.txt",
        summary=build_summary(changes), changes=changes,
    )

    repository.save_comparison(conn, comparison, old_id, new_id)
    fetched = repository.get_comparison(conn, "cmp-3")

    assert fetched.changes[0].source == "Body"


def test_existing_database_missing_source_column_gets_migrated(tmp_path):
    db_path = str(tmp_path / "legacy.db")
    # Simulate a database created before the `source` column existed - this is
    # exactly the shape of the real backend/app.db file found during planning.
    legacy_conn = sqlite3.connect(db_path)
    legacy_conn.execute("""
        CREATE TABLE changes (
            id TEXT PRIMARY KEY, comparison_id TEXT NOT NULL, section TEXT, change_type TEXT,
            old_text TEXT, new_text TEXT, old_page INTEGER, new_page INTEGER, confidence REAL,
            ai_risk_level TEXT, reviewer_risk_level TEXT, reason TEXT, reviewer_comment TEXT,
            accepted INTEGER DEFAULT 0
        )
    """)
    legacy_conn.commit()
    legacy_conn.close()

    conn = get_connection(db_path)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(changes)").fetchall()}

    assert "source" in columns
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `backend/`): `pytest tests/test_repository.py -v -k "source or migrated"`
Expected: FAIL — `changes` table has no `source` column yet, so the INSERT in `save_comparison` will raise `sqlite3.OperationalError`, and the migration test will find no `source` column since the migration helper doesn't exist yet.

- [ ] **Step 3: Add the `source` column and the migration helper**

In `backend/app/db.py`, find:

```python
CREATE TABLE IF NOT EXISTS changes (
    id TEXT PRIMARY KEY,
    comparison_id TEXT NOT NULL,
    section TEXT,
    change_type TEXT,
    old_text TEXT,
    new_text TEXT,
    old_page INTEGER,
    new_page INTEGER,
    confidence REAL,
    ai_risk_level TEXT,
    reviewer_risk_level TEXT,
    reason TEXT,
    reviewer_comment TEXT,
    accepted INTEGER DEFAULT 0
);
"""


def get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn
```

Replace with:

```python
CREATE TABLE IF NOT EXISTS changes (
    id TEXT PRIMARY KEY,
    comparison_id TEXT NOT NULL,
    section TEXT,
    change_type TEXT,
    old_text TEXT,
    new_text TEXT,
    old_page INTEGER,
    new_page INTEGER,
    confidence REAL,
    ai_risk_level TEXT,
    reviewer_risk_level TEXT,
    reason TEXT,
    reviewer_comment TEXT,
    accepted INTEGER DEFAULT 0,
    source TEXT DEFAULT 'Body'
);
"""


def _ensure_changes_source_column(conn: sqlite3.Connection) -> None:
    # CREATE TABLE IF NOT EXISTS above only applies to brand-new databases - it does
    # not add columns to a changes table that already exists from before this field
    # was introduced. Any pre-existing database (including the real backend/app.db
    # file already in use) needs this explicit, idempotent migration instead.
    columns = {row[1] for row in conn.execute("PRAGMA table_info(changes)").fetchall()}
    if "source" not in columns:
        conn.execute("ALTER TABLE changes ADD COLUMN source TEXT DEFAULT 'Body'")
        conn.commit()


def get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _ensure_changes_source_column(conn)
    return conn
```

- [ ] **Step 4: Persist and reload `source` in `repository.py`**

In `backend/app/repository.py`, find `save_comparison`:

```python
def save_comparison(conn, comparison: ComparisonResult, old_document_id: str, new_document_id: str) -> None:
    conn.execute(
        "INSERT INTO comparisons (id, old_document_id, new_document_id, created_at) VALUES (?, ?, ?, ?)",
        (comparison.comparison_id, old_document_id, new_document_id, datetime.now(timezone.utc).isoformat()),
    )
    for c in comparison.changes:
        conn.execute(
            """INSERT INTO changes
               (id, comparison_id, section, change_type, old_text, new_text, old_page, new_page,
                confidence, ai_risk_level, reviewer_risk_level, reason, reviewer_comment, accepted)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                c.change_id, comparison.comparison_id, c.section, c.change_type, c.old_text, c.new_text,
                c.old_page, c.new_page, c.confidence, c.ai_risk_level, c.reviewer_risk_level, c.reason,
                c.reviewer_comment, int(c.accepted),
            ),
        )
    conn.commit()
```

Replace with:

```python
def save_comparison(conn, comparison: ComparisonResult, old_document_id: str, new_document_id: str) -> None:
    conn.execute(
        "INSERT INTO comparisons (id, old_document_id, new_document_id, created_at) VALUES (?, ?, ?, ?)",
        (comparison.comparison_id, old_document_id, new_document_id, datetime.now(timezone.utc).isoformat()),
    )
    for c in comparison.changes:
        conn.execute(
            """INSERT INTO changes
               (id, comparison_id, section, change_type, old_text, new_text, old_page, new_page,
                confidence, ai_risk_level, reviewer_risk_level, reason, reviewer_comment, accepted, source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                c.change_id, comparison.comparison_id, c.section, c.change_type, c.old_text, c.new_text,
                c.old_page, c.new_page, c.confidence, c.ai_risk_level, c.reviewer_risk_level, c.reason,
                c.reviewer_comment, int(c.accepted), c.source,
            ),
        )
    conn.commit()
```

Find `_row_to_change`:

```python
def _row_to_change(row) -> Change:
    return Change(
        change_id=row["id"], section=row["section"], change_type=row["change_type"],
        old_text=row["old_text"], new_text=row["new_text"], old_page=row["old_page"],
        new_page=row["new_page"], confidence=row["confidence"], ai_risk_level=row["ai_risk_level"],
        reason=row["reason"], reviewer_risk_level=row["reviewer_risk_level"],
        reviewer_comment=row["reviewer_comment"], accepted=bool(row["accepted"]),
    )
```

Replace with:

```python
def _row_to_change(row) -> Change:
    return Change(
        change_id=row["id"], section=row["section"], change_type=row["change_type"],
        old_text=row["old_text"], new_text=row["new_text"], old_page=row["old_page"],
        new_page=row["new_page"], confidence=row["confidence"], ai_risk_level=row["ai_risk_level"],
        reason=row["reason"], reviewer_risk_level=row["reviewer_risk_level"],
        reviewer_comment=row["reviewer_comment"], accepted=bool(row["accepted"]),
        source=row["source"] if row["source"] is not None else "Body",
    )
```

- [ ] **Step 5: Run the new tests, then the full backend suite**

Run: `pytest tests/test_repository.py -v`
Expected: PASS — all pre-existing tests plus the 3 new ones.

Run (from `backend/`): `pytest -v`
Expected: PASS — full backend suite, no regressions.

- [ ] **Step 6: Verify the migration against the real, already-existing database**

Run (from `backend/`):
```bash
python -c "
from app.db import get_connection
conn = get_connection('app.db')
columns = {row[1] for row in conn.execute('PRAGMA table_info(changes)').fetchall()}
print('source' in columns)
"
```
Expected: prints `True` — confirms the real `app.db` file (not just test fixtures) gets migrated correctly the moment the app next connects to it. This does not modify or lose any existing data; it only adds the new column with its default value for all pre-existing rows.

- [ ] **Step 7: Commit**

```bash
git add backend/app/db.py backend/app/repository.py backend/tests/test_repository.py
git commit -m "feat: persist Change.source to SQLite, with a migration for pre-existing databases"
```

---

### Task 3: Compute `source` and rewrite wording for table-sourced structural changes

**Files:**
- Modify: `backend/app/pipeline.py`
- Test: `backend/tests/test_pipeline.py`

**Interfaces:**
- Consumes: `Paragraph.from_table` and `Change.source` from Task 1.
- Produces: no new function names — `_build_paragraph_changes` and `compare_documents` internals change to compute and set `source`, and to rewrite `change_type`/`reason` for the three generic structural types when source is `"Table"`.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_pipeline.py`:

```python
def test_table_cell_deletion_gets_table_labeled_change_type():
    old_paragraphs = [Paragraph(text="Old Row Value", from_table=True)]
    new_paragraphs = []

    result = pipeline.compare_documents(old_paragraphs, new_paragraphs, "old.docx", "new.docx")

    assert len(result.changes) == 1
    change = result.changes[0]
    assert change.source == "Table"
    assert change.change_type == "deleted_table_content"
    assert change.reason == "Table content removed."


def test_table_cell_addition_gets_table_labeled_change_type():
    old_paragraphs = []
    new_paragraphs = [Paragraph(text="New Row Value", from_table=True)]

    result = pipeline.compare_documents(old_paragraphs, new_paragraphs, "old.docx", "new.docx")

    assert len(result.changes) == 1
    change = result.changes[0]
    assert change.source == "Table"
    assert change.change_type == "added_table_content"
    assert change.reason == "New table content added."


def test_body_paragraph_addition_keeps_generic_change_type():
    old_paragraphs = []
    new_paragraphs = [Paragraph(text="New body sentence.")]

    result = pipeline.compare_documents(old_paragraphs, new_paragraphs, "old.docx", "new.docx")

    assert len(result.changes) == 1
    change = result.changes[0]
    assert change.source == "Body"
    assert change.change_type == "added_paragraph"
    assert change.reason == "New paragraph added."


def test_table_cell_with_precise_regex_change_keeps_precise_type():
    old_paragraphs = [Paragraph(text="Weigh 10 mg of sample.", from_table=True)]
    new_paragraphs = [Paragraph(text="Weigh 20 mg of sample.", from_table=True)]

    result = pipeline.compare_documents(old_paragraphs, new_paragraphs, "old.docx", "new.docx")

    assert len(result.changes) == 1
    change = result.changes[0]
    assert change.source == "Table"
    assert change.change_type == "numeric_change"
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `backend/`): `pytest tests/test_pipeline.py -v -k "table_labeled or keeps_generic or keeps_precise"`
Expected: FAIL — `Change.source` isn't computed anywhere yet, so it stays at its `"Body"` default even for table-sourced paragraphs, and `change_type` stays generic (`added_paragraph`/`deleted_paragraph`) instead of the table-aware variant.

- [ ] **Step 3: Compute `source` and rewrite wording in `pipeline.py`**

In `backend/app/pipeline.py`, find `_build_paragraph_changes`:

```python
def _build_paragraph_changes(
    section_heading: str, old_p: Paragraph, new_p: Paragraph
) -> tuple[list[Change], dict[str, list[str]]]:
    detections = regex_detectors.detect_all_regex_changes(old_p.text, new_p.text)
    changes: list[Change] = []
    for detection in detections:
        changes.append(Change(
            change_id=str(uuid.uuid4()), section=section_heading, change_type=detection.change_type,
            old_text=old_p.text, new_text=new_p.text, old_page=old_p.page, new_page=new_p.page,
            confidence=detection.confidence, ai_risk_level=risk_rules.assign_risk(detection.change_type),
            reason=detection.reason,
        ))

    already_detected_by_id: dict[str, list[str]] = {}
    stripped_old, stripped_new = regex_detectors.strip_detected_values(old_p.text, new_p.text, detections)
    if stripped_old != stripped_new:
        pending_id = str(uuid.uuid4())
        changes.append(Change(
            change_id=pending_id, section=section_heading, change_type="pending_llm_classification",
            old_text=old_p.text, new_text=new_p.text, old_page=old_p.page, new_page=new_p.page,
            confidence=0.0, ai_risk_level="Medium", reason="",
        ))
        already_detected_by_id[pending_id] = [d.change_type for d in detections]

    return changes, already_detected_by_id
```

Replace with:

```python
def _build_paragraph_changes(
    section_heading: str, old_p: Paragraph, new_p: Paragraph
) -> tuple[list[Change], dict[str, list[str]]]:
    source = "Table" if (old_p.from_table or new_p.from_table) else "Body"
    detections = regex_detectors.detect_all_regex_changes(old_p.text, new_p.text)
    changes: list[Change] = []
    for detection in detections:
        changes.append(Change(
            change_id=str(uuid.uuid4()), section=section_heading, change_type=detection.change_type,
            old_text=old_p.text, new_text=new_p.text, old_page=old_p.page, new_page=new_p.page,
            confidence=detection.confidence, ai_risk_level=risk_rules.assign_risk(detection.change_type),
            reason=detection.reason, source=source,
        ))

    already_detected_by_id: dict[str, list[str]] = {}
    stripped_old, stripped_new = regex_detectors.strip_detected_values(old_p.text, new_p.text, detections)
    if stripped_old != stripped_new:
        pending_id = str(uuid.uuid4())
        changes.append(Change(
            change_id=pending_id, section=section_heading, change_type="pending_llm_classification",
            old_text=old_p.text, new_text=new_p.text, old_page=old_p.page, new_page=new_p.page,
            confidence=0.0, ai_risk_level="Medium", reason="", source=source,
        ))
        already_detected_by_id[pending_id] = [d.change_type for d in detections]

    return changes, already_detected_by_id
```

Find the moved-paragraph loop in `compare_documents`:

```python
    for mv in moved:
        changes.append(Change(
            change_id=str(uuid.uuid4()), section=f"{mv.old_section} -> {mv.new_section}",
            change_type="moved_paragraph", old_text=mv.old_paragraph.text, new_text=mv.new_paragraph.text,
            old_page=mv.old_paragraph.page, new_page=mv.new_paragraph.page, confidence=mv.score,
            ai_risk_level=risk_rules.assign_risk("moved_paragraph"),
            reason=f"Paragraph moved from '{mv.old_section}' to '{mv.new_section}'.",
        ))
```

Replace with:

```python
    for mv in moved:
        source = "Table" if (mv.old_paragraph.from_table or mv.new_paragraph.from_table) else "Body"
        if source == "Table":
            change_type = "moved_table_content"
            reason = f"Table content moved from '{mv.old_section}' to '{mv.new_section}'."
        else:
            change_type = "moved_paragraph"
            reason = f"Paragraph moved from '{mv.old_section}' to '{mv.new_section}'."
        changes.append(Change(
            change_id=str(uuid.uuid4()), section=f"{mv.old_section} -> {mv.new_section}",
            change_type=change_type, old_text=mv.old_paragraph.text, new_text=mv.new_paragraph.text,
            old_page=mv.old_paragraph.page, new_page=mv.new_paragraph.page, confidence=mv.score,
            ai_risk_level=risk_rules.assign_risk(change_type),
            reason=reason, source=source,
        ))
```

Find the deleted-paragraph loop:

```python
    for p, section in remaining_deletes:
        changes.append(Change(
            change_id=str(uuid.uuid4()), section=section, change_type="deleted_paragraph",
            old_text=p.text, new_text="", old_page=p.page, new_page=None,
            confidence=1.0, ai_risk_level=risk_rules.assign_risk("deleted_paragraph"),
            reason="Paragraph removed.",
        ))
```

Replace with:

```python
    for p, section in remaining_deletes:
        source = "Table" if p.from_table else "Body"
        if source == "Table":
            change_type = "deleted_table_content"
            reason = "Table content removed."
        else:
            change_type = "deleted_paragraph"
            reason = "Paragraph removed."
        changes.append(Change(
            change_id=str(uuid.uuid4()), section=section, change_type=change_type,
            old_text=p.text, new_text="", old_page=p.page, new_page=None,
            confidence=1.0, ai_risk_level=risk_rules.assign_risk(change_type),
            reason=reason, source=source,
        ))
```

Find the added-paragraph loop:

```python
    for p, section in remaining_inserts:
        changes.append(Change(
            change_id=str(uuid.uuid4()), section=section, change_type="added_paragraph",
            old_text="", new_text=p.text, old_page=None, new_page=p.page,
            confidence=1.0, ai_risk_level=risk_rules.assign_risk("added_paragraph"),
            reason="New paragraph added.",
        ))
```

Replace with:

```python
    for p, section in remaining_inserts:
        source = "Table" if p.from_table else "Body"
        if source == "Table":
            change_type = "added_table_content"
            reason = "New table content added."
        else:
            change_type = "added_paragraph"
            reason = "New paragraph added."
        changes.append(Change(
            change_id=str(uuid.uuid4()), section=section, change_type=change_type,
            old_text="", new_text=p.text, old_page=None, new_page=p.page,
            confidence=1.0, ai_risk_level=risk_rules.assign_risk(change_type),
            reason=reason, source=source,
        ))
```

The `pending_llm_classification` resolution loop near the end of `compare_documents` (the one applying `classify_changes_batch` results) does not need any change — `source` was already set correctly when the pending placeholder `Change` was created above, and that loop never touches `c.source`.

- [ ] **Step 4: Run the new tests, then the full backend suite**

Run: `pytest tests/test_pipeline.py -v`
Expected: PASS — all pre-existing tests (including `test_pipeline_reproduces_the_outline_example` and the severity-masking test from earlier plans, none of which use `from_table`, so all their changes now correctly show `source == "Body"`) plus the 4 new ones.

Run (from `backend/`): `pytest -v`
Expected: PASS — full backend suite, no regressions. Pay attention to `backend/tests/test_api.py`'s comparison-flow test too — confirm it still passes (it doesn't use table content, so `source` should be `"Body"` throughout and its existing assertions are unaffected).

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipeline.py backend/tests/test_pipeline.py
git commit -m "feat: compute Change.source and rewrite wording for table-sourced structural changes"
```

---

### Task 4: Surface `source` through export and the frontend

**Files:**
- Modify: `backend/app/export.py`
- Modify: `frontend/pages/2_Detailed_Changes.py`
- Test: `backend/tests/test_export.py`

**Interfaces:**
- Consumes: `Change.source` from Task 1, actually populated with real values by Task 3.
- Produces: no new function names — `to_json`/`to_csv` gain the `source` field/column, and the frontend table gains a "Source" column.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_export.py`:

```python
def test_to_json_includes_source_field():
    comparison = make_comparison()
    comparison.changes[0].source = "Table"
    result = to_json(comparison)
    assert result["changes"][0]["source"] == "Table"


def test_to_json_defaults_source_to_body():
    result = to_json(make_comparison())
    assert result["changes"][0]["source"] == "Body"


def test_to_csv_includes_source_column():
    comparison = make_comparison()
    comparison.changes[0].source = "Table"
    csv_text = to_csv(comparison)
    rows = list(csv.reader(io.StringIO(csv_text)))
    assert "source" in rows[0]
    source_index = rows[0].index("source")
    assert rows[1][source_index] == "Table"
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `backend/`): `pytest tests/test_export.py -v -k source`
Expected: FAIL — `to_json`/`to_csv` don't include `source` anywhere yet.

- [ ] **Step 3: Add `source` to `to_json` and `to_csv`**

In `backend/app/export.py`, find:

```python
        "changes": [
            {
                "change_id": c.change_id,
                "section": c.section,
                "change_type": c.change_type,
                "old_text": c.old_text,
                "new_text": c.new_text,
                "risk_level": _effective_risk(c),
                "ai_risk_level": c.ai_risk_level,
                "reviewer_risk_level": c.reviewer_risk_level,
                "reason": c.reason,
                "old_page": c.old_page,
                "new_page": c.new_page,
                "confidence": c.confidence,
                "reviewer_comment": c.reviewer_comment,
                "accepted": c.accepted,
            }
            for c in comparison.changes
        ],
```

Replace with:

```python
        "changes": [
            {
                "change_id": c.change_id,
                "section": c.section,
                "change_type": c.change_type,
                "source": c.source,
                "old_text": c.old_text,
                "new_text": c.new_text,
                "risk_level": _effective_risk(c),
                "ai_risk_level": c.ai_risk_level,
                "reviewer_risk_level": c.reviewer_risk_level,
                "reason": c.reason,
                "old_page": c.old_page,
                "new_page": c.new_page,
                "confidence": c.confidence,
                "reviewer_comment": c.reviewer_comment,
                "accepted": c.accepted,
            }
            for c in comparison.changes
        ],
```

Find `to_csv`:

```python
def to_csv(comparison: ComparisonResult) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "change_id", "section", "change_type", "old_text", "new_text",
        "risk_level", "reason", "old_page", "new_page", "confidence",
        "reviewer_comment", "accepted",
    ])
    for c in comparison.changes:
        writer.writerow([
            c.change_id, c.section, c.change_type, c.old_text, c.new_text,
            _effective_risk(c), c.reason, c.old_page, c.new_page,
            c.confidence, c.reviewer_comment or "", c.accepted,
        ])
    return output.getvalue()
```

Replace with:

```python
def to_csv(comparison: ComparisonResult) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "change_id", "section", "change_type", "source", "old_text", "new_text",
        "risk_level", "reason", "old_page", "new_page", "confidence",
        "reviewer_comment", "accepted",
    ])
    for c in comparison.changes:
        writer.writerow([
            c.change_id, c.section, c.change_type, c.source, c.old_text, c.new_text,
            _effective_risk(c), c.reason, c.old_page, c.new_page,
            c.confidence, c.reviewer_comment or "", c.accepted,
        ])
    return output.getvalue()
```

- [ ] **Step 4: Add the "Source" column to the frontend table**

In `frontend/pages/2_Detailed_Changes.py`, find:

```python
    st.table([
        {
            "Section": c["section"],
            "Old Text": c["old_text"],
            "New Text": c["new_text"],
            "Change Type": c["change_type"],
            "Risk": c.get("reviewer_risk_level") or c["ai_risk_level"],
            "Reason": c["reason"],
        }
        for c in filtered
    ])
```

Replace with:

```python
    st.table([
        {
            "Section": c["section"],
            "Source": c["source"],
            "Old Text": c["old_text"],
            "New Text": c["new_text"],
            "Change Type": c["change_type"],
            "Risk": c.get("reviewer_risk_level") or c["ai_risk_level"],
            "Reason": c["reason"],
        }
        for c in filtered
    ])
```

- [ ] **Step 5: Run the new tests, then the full backend suite**

Run: `pytest tests/test_export.py -v`
Expected: PASS — all pre-existing tests plus the 3 new ones.

Run (from `backend/`): `pytest -v`
Expected: PASS — full backend suite, no regressions.

- [ ] **Step 6: Manually verify end-to-end against the real demo file**

Run (from `backend/`):
```bash
python -c "
from app.extraction import extract_text
from app.pipeline import compare_documents

old = extract_text('../test-documents/docx/TableHeaderFooterDemo_v1.docx', 'docx')
new = extract_text('../test-documents/docx/TableHeaderFooterDemo_v2.docx', 'docx')
result = compare_documents(old, new, 'v1.docx', 'v2.docx')
for c in result.changes:
    print(f'{c.source:6} {c.change_type:24} [{c.section}]: {c.old_text!r} -> {c.new_text!r}')
"
```
Expected: the cell-value change under "2.0 Acceptance Criteria" shows `Table  numeric_change` (precise type preserved), the new row's additions show `Table  added_table_content` (rewritten wording), and the header/footer/scope/approval changes all show `Body`.

- [ ] **Step 7: Commit**

```bash
git add backend/app/export.py frontend/pages/2_Detailed_Changes.py backend/tests/test_export.py
git commit -m "feat: surface Change.source through export and the Detailed Changes table"
```
