# DOCX Tables, Headers & Footers Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `_extract_docx` picks up content the app currently misses entirely — table cells (including nested tables) and non-inherited page headers/footers — without touching any other pipeline stage.

**Architecture:** Tables are folded directly into the body's paragraph stream via `doc.iter_inner_content()` (yields paragraphs and tables interleaved in true document order), recursing into every cell so nested tables are handled the same way as top-level ones. Since this produces real python-docx `Paragraph` objects, all existing heading-detection logic applies unchanged. Headers/footers can't be positioned in reading order the same way, so they become two synthetic pseudo-sections ("Page Header", "Page Footer") appended after the body content, reusing the exact same downstream pipeline.

**Tech Stack:** `python-docx` 1.2.0 (already installed, `iter_inner_content()` confirmed present on `Document`, headers, footers, and table cells). No new dependencies.

## Global Constraints

- No new dependencies.
- Table granularity is **per cell** — each cell becomes its own paragraph-equivalent, not per-row or per-whole-table.
- Table cells are folded directly into the body's paragraph stream in document order (not a separate parallel structure) — a table under a heading becomes part of that heading's section automatically.
- Headers/footers become pseudo-sections named exactly `"Page Header"` and `"Page Footer"`, appended after body content — never emitted if there's no actual header/footer content (skip `is_linked_to_previous` sections, and skip entirely if the resulting paragraph list is empty).
- Multiple distinct (non-linked) headers across different Word sections combine into one `"Page Header"` section (same for footers) — no per-section numbering.
- Out of scope: `first_page_header`/`even_page_header` variants, footnotes, text boxes, comments, endnotes, content controls, embedded objects. Do not touch PDF or TXT extraction.
- `backend/app/models.py`, `sectioning.py`, `section_matching.py`, `paragraph_diff.py`, `move_reconciliation.py`, `pipeline.py`, `regex_detectors.py`, `llm_classifier.py`, `risk_rules.py`, `export.py`, and the frontend must not change — if a task discovers a need to touch any of these, stop and flag it rather than making an undocumented change.

---

### Task 1: Fold table cells into the body paragraph stream

**Files:**
- Modify: `backend/app/extraction.py`
- Test: `backend/tests/test_extraction.py`

**Interfaces:**
- Consumes: nothing new — this task only touches `extraction.py`'s own existing helpers (`_docx_paragraph_font_size_pt`, `_docx_body_baseline_pt`, `HEADING_STYLE_PREFIXES`, `DOCX_HEADING_SIZE_DELTA_PT`, `_looks_like_heading_shape`).
- Produces: `_iter_docx_paragraphs(content_iter) -> Iterator[docx.text.paragraph.Paragraph]` and `_docx_paragraph_to_model(para, index: int, baseline_pt: float) -> Paragraph | None` (returns `None` for an empty/whitespace-only paragraph, matching today's skip-empty behavior). Task 2 imports and calls both of these by these exact names.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_extraction.py`:

```python
def test_extract_docx_extracts_table_cell_content(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    doc.add_paragraph("5.0 Acceptance Criteria", style="Heading 1")
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Parameter"
    table.cell(0, 1).text = "Limit"
    table.cell(1, 0).text = "Assay"
    table.cell(1, 1).text = "95.0% to 105.0%"
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")
    texts = [p.text for p in paragraphs]

    assert "Parameter" in texts
    assert "Limit" in texts
    assert "Assay" in texts
    assert "95.0% to 105.0%" in texts


def test_extract_docx_extracts_nested_table_cell_content(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    table = doc.add_table(rows=1, cols=1)
    nested = table.cell(0, 0).add_table(rows=1, cols=1)
    nested.cell(0, 0).text = "Nested cell text"
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")
    texts = [p.text for p in paragraphs]

    assert "Nested cell text" in texts


def test_extract_docx_detects_word_style_heading_inside_table_cell(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    table = doc.add_table(rows=1, cols=1)
    cell = table.cell(0, 0)
    cell.paragraphs[0].text = "5.2 Sample Preparation"
    cell.paragraphs[0].style = doc.styles["Heading 1"]
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")
    heading_paragraphs = [p for p in paragraphs if p.is_heading]

    assert len(heading_paragraphs) == 1
    assert heading_paragraphs[0].text == "5.2 Sample Preparation"


def test_extract_docx_detects_font_size_heading_inside_table_cell(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    doc.add_paragraph("Weigh 10 mg of sample and dilute to volume.")
    table = doc.add_table(rows=1, cols=1)
    p = table.cell(0, 0).paragraphs[0]
    run = p.add_run("Sample Preparation")
    run.bold = True
    run.font.size = Pt(16)
    doc.add_paragraph("Inject into the HPLC system.")
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")
    heading_paragraphs = [p for p in paragraphs if p.is_heading]

    assert len(heading_paragraphs) == 1
    assert heading_paragraphs[0].text == "Sample Preparation"


def test_extract_docx_without_tables_headers_or_footers_is_unchanged(tmp_path):
    """Regression guard: this refactor must not change extraction for documents
    that don't use any of the new features."""
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    doc.add_paragraph("1.0 Scope", style="Heading 1")
    doc.add_paragraph("This procedure applies to all testing.")
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")

    assert len(paragraphs) == 2
    assert paragraphs[0].text == "1.0 Scope"
    assert paragraphs[0].is_heading is True
    assert paragraphs[1].text == "This procedure applies to all testing."
    assert paragraphs[1].is_heading is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `backend/`): `pytest tests/test_extraction.py -v -k "table_cell or nested_table or inside_table_cell"`
Expected: FAIL — table content isn't extracted at all yet (the first four tests fail); the regression test (last one) should already PASS since it doesn't touch tables — confirm this before proceeding, since it establishes your "before" baseline.

- [ ] **Step 3: Add the recursive walker, extract the per-paragraph converter, and rewire `_extract_docx`**

In `backend/app/extraction.py`, add these two imports at the top of the file (alongside the existing `from docx import Document as DocxDocument`):

```python
from docx.table import Table as DocxTable
from docx.text.paragraph import Paragraph as DocxParagraph
```

Add these two new functions (place them near `_docx_paragraph_font_size_pt`/`_docx_body_baseline_pt`):

```python
def _iter_docx_paragraphs(content_iter):
    for item in content_iter:
        if isinstance(item, DocxParagraph):
            yield item
        elif isinstance(item, DocxTable):
            for row in item.rows:
                for cell in row.cells:
                    yield from _iter_docx_paragraphs(cell.iter_inner_content())


def _docx_paragraph_to_model(para, index: int, baseline_pt: float) -> Paragraph | None:
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
    )
```

Replace the existing `_extract_docx` function body:

```python
def _extract_docx(file_path: str) -> list[Paragraph]:
    doc = DocxDocument(file_path)
    baseline_pt = _docx_body_baseline_pt(doc)

    paragraphs: list[Paragraph] = []
    index = 0
    for para in _iter_docx_paragraphs(doc.iter_inner_content()):
        model = _docx_paragraph_to_model(para, index, baseline_pt)
        if model is not None:
            paragraphs.append(model)
            index += 1
    return paragraphs
```

- [ ] **Step 4: Run the new tests, then the full extraction suite**

Run: `pytest tests/test_extraction.py -v`
Expected: PASS — all pre-existing DOCX/PDF/TXT tests (regression guard confirms byte-identical behavior for plain documents) plus the 5 new ones.

Run (from `backend/`): `pytest -v`
Expected: PASS — full backend suite, no regressions in downstream stages that consume `Paragraph`/`Section` objects.

- [ ] **Step 5: Commit**

```bash
git add backend/app/extraction.py backend/tests/test_extraction.py
git commit -m "feat: fold DOCX table cells into the body paragraph stream"
```

---

### Task 2: Extract non-inherited headers/footers as pseudo-sections

**Files:**
- Modify: `backend/app/extraction.py`
- Test: `backend/tests/test_extraction.py`

**Interfaces:**
- Consumes: `_iter_docx_paragraphs(content_iter)` and `_docx_paragraph_to_model(para, index, baseline_pt)` from Task 1, unmodified.
- Produces: no new function names — only `_extract_docx`'s internal body changes to also emit header/footer pseudo-sections.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_extraction.py`:

```python
def test_extract_docx_adds_page_header_section_when_header_is_set(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    doc.add_paragraph("Body content here.")
    doc.sections[0].header.paragraphs[0].text = "Confidential SOP-1234"
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")
    texts = [p.text for p in paragraphs]

    assert "Page Header" in texts
    header_index = texts.index("Page Header")
    assert paragraphs[header_index].is_heading is True
    assert "Confidential SOP-1234" in texts
    assert "Page Footer" not in texts


def test_extract_docx_adds_page_footer_section_when_footer_is_set(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    doc.add_paragraph("Body content here.")
    doc.sections[0].footer.paragraphs[0].text = "Page footer text"
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")
    texts = [p.text for p in paragraphs]

    assert "Page Footer" in texts
    footer_index = texts.index("Page Footer")
    assert paragraphs[footer_index].is_heading is True
    assert "Page footer text" in texts
    assert "Page Header" not in texts


def test_extract_docx_omits_page_header_and_footer_when_neither_is_set(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    doc.add_paragraph("Body content here.")
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")
    texts = [p.text for p in paragraphs]

    assert "Page Header" not in texts
    assert "Page Footer" not in texts


def test_extract_docx_page_header_and_footer_both_present_appear_in_order(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    doc.add_paragraph("Body content here.")
    doc.sections[0].header.paragraphs[0].text = "Header text"
    doc.sections[0].footer.paragraphs[0].text = "Footer text"
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")
    texts = [p.text for p in paragraphs]

    assert texts.index("Page Header") < texts.index("Header text")
    assert texts.index("Header text") < texts.index("Page Footer")
    assert texts.index("Page Footer") < texts.index("Footer text")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_extraction.py -v -k "page_header or page_footer"`
Expected: FAIL — no header/footer extraction exists yet.

- [ ] **Step 3: Extend `_extract_docx` to collect and append header/footer pseudo-sections**

In `backend/app/extraction.py`, replace `_extract_docx`'s body again:

```python
def _extract_docx(file_path: str) -> list[Paragraph]:
    doc = DocxDocument(file_path)
    baseline_pt = _docx_body_baseline_pt(doc)

    paragraphs: list[Paragraph] = []
    index = 0
    for para in _iter_docx_paragraphs(doc.iter_inner_content()):
        model = _docx_paragraph_to_model(para, index, baseline_pt)
        if model is not None:
            paragraphs.append(model)
            index += 1

    header_paragraphs = []
    footer_paragraphs = []
    for section in doc.sections:
        if not section.header.is_linked_to_previous:
            header_paragraphs.extend(_iter_docx_paragraphs(section.header.iter_inner_content()))
        if not section.footer.is_linked_to_previous:
            footer_paragraphs.extend(_iter_docx_paragraphs(section.footer.iter_inner_content()))

    if header_paragraphs:
        paragraphs.append(Paragraph(text="Page Header", paragraph_index=index, is_heading=True))
        index += 1
        for para in header_paragraphs:
            model = _docx_paragraph_to_model(para, index, baseline_pt)
            if model is not None:
                paragraphs.append(model)
                index += 1

    if footer_paragraphs:
        paragraphs.append(Paragraph(text="Page Footer", paragraph_index=index, is_heading=True))
        index += 1
        for para in footer_paragraphs:
            model = _docx_paragraph_to_model(para, index, baseline_pt)
            if model is not None:
                paragraphs.append(model)
                index += 1

    return paragraphs
```

- [ ] **Step 4: Run the new tests, then the full backend suite**

Run: `pytest tests/test_extraction.py -v`
Expected: PASS — all tests from Task 1 (still passing, confirming this task didn't regress table extraction) plus the 4 new ones.

Run (from `backend/`): `pytest -v`
Expected: PASS — full backend suite, no regressions. Pay particular attention to `test_extract_docx_without_tables_headers_or_footers_is_unchanged` from Task 1 — it must still assert exactly 2 paragraphs, confirming a header/footer-free, table-free document is completely unaffected by this task too.

- [ ] **Step 5: Commit**

```bash
git add backend/app/extraction.py backend/tests/test_extraction.py
git commit -m "feat: extract DOCX headers/footers as Page Header/Page Footer pseudo-sections"
```
