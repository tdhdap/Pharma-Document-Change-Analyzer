# DOCX Table/Header/Footer Heading False-Positive Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Table-cell and header/footer text no longer gets misdetected as its own heading by the ALL-CAPS/numbered-pattern text-pattern fallback — short values like "HPLC", "NMT 0.5%", "CONFIDENTIAL" stay as body content under the section they actually belong to.

**Architecture:** A new `Paragraph.allow_text_pattern_heading` field (default `True`, preserving today's behavior everywhere) gates whether `sectioning.py`'s ALL-CAPS/numbered-pattern checks run at all for a given paragraph. DOCX extraction sets it to `False` for table-cell and header/footer paragraphs; structural signals (Word style, font-size) are completely unaffected and still work everywhere.

**Tech Stack:** Existing backend only — `backend/app/models.py`, `backend/app/sectioning.py`, `backend/app/extraction.py`. No new dependencies.

## Global Constraints

- `Paragraph.allow_text_pattern_heading: bool = True` — additive field, default `True` preserves today's behavior for every paragraph not explicitly touched by this fix (all TXT/PDF paragraphs, all DOCX body paragraphs).
- Structural heading signals (`Paragraph.is_heading`, resolved during extraction from Word style / font-size / PDF TOC) are checked *before* `allow_text_pattern_heading` in `sectioning.py` and are never gated by it — a genuinely styled or oversized-font heading inside a table cell or header must still be detected.
- DOCX-only. `_extract_pdf` and `_extract_txt` are untouched — PDF has no structural concept of "this text came from a table cell."
- Table-cell paragraphs get `allow_text_pattern_heading=False` regardless of where the table sits (body, header, or footer). Header/footer paragraphs get `allow_text_pattern_heading=False` whether they're direct paragraphs or inside a nested table.
- `_looks_like_all_caps_heading`, `_looks_like_numbered_heading`, `_looks_like_heading_shape`, `_docx_paragraph_font_size_pt`, `_docx_body_baseline_pt`, `HEADING_STYLE_PREFIXES`, `DOCX_HEADING_SIZE_DELTA_PT` are all unchanged — this plan does not modify any existing detection logic, only which paragraphs are allowed to be tested against the text-pattern rules.

---

### Task 1: Add `allow_text_pattern_heading` and gate the text-pattern fallback

**Files:**
- Modify: `backend/app/models.py`
- Modify: `backend/app/sectioning.py`
- Test: `backend/tests/test_sectioning.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `Paragraph.allow_text_pattern_heading: bool = True` (new field on an existing dataclass). Task 2 constructs `Paragraph` instances passing this field by this exact name.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_sectioning.py`:

```python
def test_all_caps_paragraph_with_text_pattern_disallowed_is_not_a_heading():
    paragraphs = [
        Paragraph(text="2.0 Acceptance Criteria", is_heading=True),
        Paragraph(text="Assay", allow_text_pattern_heading=False),
        Paragraph(text="HPLC", allow_text_pattern_heading=False),
    ]

    sections = split_into_sections(paragraphs)

    assert len(sections) == 1
    assert sections[0].heading == "2.0 Acceptance Criteria"
    assert [p.text for p in sections[0].paragraphs] == ["Assay", "HPLC"]


def test_numbered_pattern_with_text_pattern_disallowed_is_not_a_heading():
    paragraphs = [
        Paragraph(text="2.0 Acceptance Criteria", is_heading=True),
        Paragraph(text="1.0 mg", allow_text_pattern_heading=False),
    ]

    sections = split_into_sections(paragraphs)

    assert len(sections) == 1
    assert sections[0].heading == "2.0 Acceptance Criteria"
    assert [p.text for p in sections[0].paragraphs] == ["1.0 mg"]


def test_all_caps_body_paragraph_is_still_a_heading_by_default():
    """Regression guard: allow_text_pattern_heading defaults to True, so
    existing ALL-CAPS body-paragraph detection is completely unaffected."""
    paragraphs = [
        Paragraph(text="SCOPE"),
        Paragraph(text="This procedure applies to all lab testing."),
        Paragraph(text="MATERIALS"),
    ]

    sections = split_into_sections(paragraphs)

    assert len(sections) == 2
    assert sections[0].heading == "SCOPE"
    assert sections[1].heading == "MATERIALS"


def test_structural_signal_still_wins_when_text_pattern_disallowed():
    paragraphs = [
        Paragraph(text="Sample Preparation", is_heading=True, allow_text_pattern_heading=False),
        Paragraph(text="Weigh 10 mg of sample.", allow_text_pattern_heading=False),
    ]

    sections = split_into_sections(paragraphs)

    assert len(sections) == 1
    assert sections[0].heading == "Sample Preparation"
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `backend/`): `pytest tests/test_sectioning.py -v -k "text_pattern_disallowed or still_a_heading_by_default"`
Expected: FAIL — `Paragraph` has no `allow_text_pattern_heading` field yet, so construction raises `TypeError: __init__() got an unexpected keyword argument`.

- [ ] **Step 3: Add the field and gate the check**

In `backend/app/models.py`, find:

```python
@dataclass
class Paragraph:
    text: str
    page: Optional[int] = None
    paragraph_index: Optional[int] = None
    is_heading: bool = False
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
```

In `backend/app/sectioning.py`, find:

```python
def _is_heading_paragraph(p: Paragraph) -> bool:
    if p.is_heading:
        return True
    if _looks_like_numbered_heading(p.text):
        return True
    if _looks_like_all_caps_heading(p.text):
        return True
    return False
```

Replace with:

```python
def _is_heading_paragraph(p: Paragraph) -> bool:
    if p.is_heading:
        return True
    if not p.allow_text_pattern_heading:
        return False
    if _looks_like_numbered_heading(p.text):
        return True
    if _looks_like_all_caps_heading(p.text):
        return True
    return False
```

- [ ] **Step 4: Run the new tests, then the full sectioning suite**

Run: `pytest tests/test_sectioning.py -v`
Expected: PASS — all 9 pre-existing tests (unaffected, since they never pass `allow_text_pattern_heading` and the default `True` preserves their behavior exactly) plus the 4 new ones.

Run (from `backend/`): `pytest -v`
Expected: PASS — full backend suite, no regressions.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models.py backend/app/sectioning.py backend/tests/test_sectioning.py
git commit -m "feat: gate ALL-CAPS/numbered heading detection behind allow_text_pattern_heading"
```

---

### Task 2: Wire the flag through DOCX table/header/footer extraction

**Files:**
- Modify: `backend/app/extraction.py`
- Test: `backend/tests/test_extraction.py`

**Interfaces:**
- Consumes: `Paragraph.allow_text_pattern_heading` from Task 1.
- Produces: no new function names — `_iter_docx_paragraphs` changes its yield shape (from bare `DocxParagraph` to `(DocxParagraph, bool)` tuples), and `_docx_paragraph_to_model` gains a new parameter. Nothing outside `extraction.py` calls either function, so this is a contained signature change.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_extraction.py`:

```python
def test_extract_docx_all_caps_table_cell_stays_in_its_section(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    doc.add_paragraph("2.0 Acceptance Criteria", style="Heading 1")
    table = doc.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Method"
    table.cell(0, 1).text = "HPLC"
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")
    heading_paragraphs = [p for p in paragraphs if p.is_heading]

    assert len(heading_paragraphs) == 1
    assert heading_paragraphs[0].text == "2.0 Acceptance Criteria"
    texts = [p.text for p in paragraphs]
    assert "HPLC" in texts


def test_extract_docx_all_caps_header_text_stays_in_page_header_section(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    doc.add_paragraph("Body content here.")
    doc.sections[0].header.paragraphs[0].text = "CONFIDENTIAL"
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")
    heading_paragraphs = [p for p in paragraphs if p.is_heading]

    assert len(heading_paragraphs) == 1
    assert heading_paragraphs[0].text == "Page Header"
    texts = [p.text for p in paragraphs]
    assert "CONFIDENTIAL" in texts


def test_extract_docx_font_size_heading_inside_table_cell_still_detected(tmp_path):
    """Regression guard: structural signals (font-size) must still work
    inside table cells even though the text-pattern fallback is now
    disallowed there."""
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    doc.add_paragraph("Weigh 10 mg of sample and dilute to volume.")
    table = doc.add_table(rows=1, cols=1)
    p = table.cell(0, 0).paragraphs[0]
    run = p.add_run("Sample Preparation")
    run.bold = True
    run.font.size = Pt(16)
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")
    heading_paragraphs = [p for p in paragraphs if p.is_heading]

    assert len(heading_paragraphs) == 1
    assert heading_paragraphs[0].text == "Sample Preparation"


def test_extract_docx_all_caps_body_paragraph_still_a_heading(tmp_path):
    """Regression guard: body-paragraph ALL-CAPS detection (not from a
    table or header/footer) is completely unaffected by this change."""
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    doc.add_paragraph("SCOPE")
    doc.add_paragraph("This procedure applies to all lab testing.")
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")
    heading_paragraphs = [p for p in paragraphs if p.is_heading]

    assert len(heading_paragraphs) == 1
    assert heading_paragraphs[0].text == "SCOPE"
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `backend/`): `pytest tests/test_extraction.py -v -k "stays_in_its_section or stays_in_page_header or still_detected or still_a_heading"`
Expected: `test_extract_docx_all_caps_table_cell_stays_in_its_section` and `test_extract_docx_all_caps_header_text_stays_in_page_header_section` FAIL (today's code has no `allow_text_pattern_heading` concept, so "HPLC"/"CONFIDENTIAL" incorrectly become their own headings). The two regression-guard tests should already PASS — confirm this as your "before" baseline.

- [ ] **Step 3: Thread `allow_text_pattern_heading` through the extraction walk**

In `backend/app/extraction.py`, replace `_iter_docx_paragraphs`:

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

Replace `_docx_paragraph_to_model`:

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

Replace `_extract_docx`:

```python
def _extract_docx(file_path: str) -> list[Paragraph]:
    doc = DocxDocument(file_path)
    baseline_pt = _docx_body_baseline_pt(doc)

    paragraphs: list[Paragraph] = []
    index = 0
    for para, allow_text_pattern_heading in _iter_docx_paragraphs(doc.iter_inner_content()):
        model = _docx_paragraph_to_model(para, index, baseline_pt, allow_text_pattern_heading)
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

- [ ] **Step 4: Run the new tests, then the full backend suite**

Run: `pytest tests/test_extraction.py -v`
Expected: PASS — all pre-existing tests (including every test from the earlier tables/headers/footers plan — merged-cell dedup, empty-header suppression, nested tables, font-size/Word-style headings inside cells) plus the 4 new ones.

Run (from `backend/`): `pytest -v`
Expected: PASS — full backend suite, no regressions.

- [ ] **Step 5: Manually confirm against the real demo file**

Run (from `backend/`):
```bash
python -c "
from app.extraction import extract_text
from app.sectioning import split_into_sections

paragraphs = extract_text('../test-documents/docx/TableHeaderFooterDemo_v1.docx', 'docx')
sections = split_into_sections(paragraphs)
for s in sections:
    print(s.heading, '->', [p.text for p in s.paragraphs])
"
```
Expected: exactly 5 sections — `1.0 Scope`, `2.0 Acceptance Criteria` (containing all the table's cells including "HPLC" as body content, not as their own sections), `3.0 Approval`, `Page Header` (containing "Confidential - SOP-1234" as body content), `Page Footer` (containing "Uncontrolled Copy - Page 1" as body content). No section heading should be a bare table value or header/footer text.

- [ ] **Step 6: Commit**

```bash
git add backend/app/extraction.py backend/tests/test_extraction.py
git commit -m "fix: disallow text-pattern heading detection for DOCX table/header/footer paragraphs"
```
