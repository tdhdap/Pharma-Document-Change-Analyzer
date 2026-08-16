# DOCX First-Page/Even-Page Headers & Footers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract first-page and even-page header/footer variants (in addition to the existing default variant), gated by the toggles that actually control whether Word displays them, and split every section's header/footer content into its own distinctly-named pseudo-section instead of merging everything into one generic "Page Header"/"Page Footer" bucket.

**Architecture:** Two new pure(ish) helpers in `backend/app/extraction.py` — `_docx_header_footer_specs(doc)` (walks sections and toggles to produce the list of header/footer sources actually worth extracting) and `_header_footer_heading_text(...)` (computes each one's pseudo-heading text) — replace `_extract_docx`'s current combined-list logic.

**Tech Stack:** Python 3, pytest, python-docx — no new dependencies.

## Global Constraints

- First-page content (`section.first_page_header`/`first_page_footer`) is extracted ONLY when that section's `different_first_page_header_footer` is `True`.
- Even-page content (`section.even_page_header`/`even_page_footer`) is extracted ONLY when the document-level `doc.settings.odd_and_even_pages_header_footer` is `True` (checked once for the whole document, not per section).
- `is_linked_to_previous` is checked independently for the header and the footer of every variant — a variant with its own content produces a pseudo-section; a linked one is skipped (inherits, same as today's default-variant behavior).
- Heading text naming (exact strings):
  - Default variant, document has exactly 1 section → `"Page Header"` / `"Page Footer"` (unqualified — today's exact behavior, zero regression).
  - Default variant, document has 2+ sections → `"Page Header (Section 2)"` (1-indexed; every section qualified once there's more than one).
  - First-page variant, 1 section → `"Page Header (First Page)"`.
  - First-page variant, 2+ sections → `"Page Header (Section 2, First Page)"`.
  - Even-page variant follows the identical pattern with `"Even Page"`.
- Ordering: every header pseudo-section first (section order, then default → first-page → even-page within each section), then every footer pseudo-section, same order pattern.
- No changes to `db.py`, `repository.py`, `export.py`, or the frontend.
- Reference: `docs/superpowers/specs/2026-08-14-docx-header-footer-variants-design.md`.

---

### Task 1: Add the spec-collection and heading-naming helpers

**Files:**
- Modify: `backend/app/extraction.py`
- Modify: `backend/tests/test_extraction.py`

**Interfaces:**
- Produces:
  - `_docx_header_footer_specs(doc) -> list[tuple[str, int, str, object]]` in `app/extraction.py` — each tuple is `(kind, section_index, variant_label, source)` where `kind` is `"header"` or `"footer"`, `section_index` is 0-indexed, `variant_label` is `""`/`"First Page"`/`"Even Page"`, and `source` is the python-docx `_Header`/`_Footer` object to extract from. Consumed by Task 2.
  - `_header_footer_heading_text(kind: str, section_index: int, variant_label: str, multi_section: bool) -> str` in `app/extraction.py`. Consumed by Task 2.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/test_extraction.py`, replace the existing import line:

```python
from app.extraction import extract_text
```

with:

```python
from app.extraction import extract_text, _docx_header_footer_specs, _header_footer_heading_text
```

Append these test functions:

```python
def test_specs_include_default_header_and_footer_when_set():
    doc = DocxDocument()
    doc.sections[0].header.paragraphs[0].text = "Header text"
    doc.sections[0].footer.paragraphs[0].text = "Footer text"

    specs = _docx_header_footer_specs(doc)

    assert len(specs) == 2
    header_spec = next(s for s in specs if s[0] == "header")
    footer_spec = next(s for s in specs if s[0] == "footer")
    assert (header_spec[1], header_spec[2]) == (0, "")
    assert header_spec[3].paragraphs[0].text == "Header text"
    assert (footer_spec[1], footer_spec[2]) == (0, "")
    assert footer_spec[3].paragraphs[0].text == "Footer text"


def test_specs_omit_default_header_and_footer_when_unset():
    doc = DocxDocument()

    specs = _docx_header_footer_specs(doc)

    assert specs == []


def test_specs_omit_first_page_variant_when_toggle_is_off():
    doc = DocxDocument()
    doc.sections[0].first_page_header.paragraphs[0].text = "First page header text"
    # different_first_page_header_footer deliberately left False (default) - Word
    # would never actually display this content.

    specs = _docx_header_footer_specs(doc)

    assert not any(s[2] == "First Page" for s in specs)


def test_specs_include_first_page_variant_when_toggle_is_on():
    doc = DocxDocument()
    doc.sections[0].different_first_page_header_footer = True
    doc.sections[0].first_page_header.paragraphs[0].text = "First page header text"

    specs = _docx_header_footer_specs(doc)

    first_page_specs = [s for s in specs if s[2] == "First Page"]
    assert len(first_page_specs) == 1
    assert first_page_specs[0][0] == "header"
    assert first_page_specs[0][1] == 0
    assert first_page_specs[0][3].paragraphs[0].text == "First page header text"


def test_specs_omit_even_page_variant_when_document_toggle_is_off():
    doc = DocxDocument()
    doc.sections[0].even_page_header.paragraphs[0].text = "Even page header text"
    # doc.settings.odd_and_even_pages_header_footer deliberately left False (default).

    specs = _docx_header_footer_specs(doc)

    assert not any(s[2] == "Even Page" for s in specs)


def test_specs_include_even_page_variant_when_document_toggle_is_on():
    doc = DocxDocument()
    doc.settings.odd_and_even_pages_header_footer = True
    doc.sections[0].even_page_header.paragraphs[0].text = "Even page header text"

    specs = _docx_header_footer_specs(doc)

    even_page_specs = [s for s in specs if s[2] == "Even Page"]
    assert len(even_page_specs) == 1
    assert even_page_specs[0][0] == "header"
    assert even_page_specs[0][3].paragraphs[0].text == "Even page header text"


def test_specs_are_ordered_all_headers_then_all_footers_across_sections():
    doc = DocxDocument()
    doc.sections[0].header.paragraphs[0].text = "Section 1 header"
    doc.sections[0].footer.paragraphs[0].text = "Section 1 footer"
    doc.add_section()
    doc.sections[1].header.is_linked_to_previous = False
    doc.sections[1].header.paragraphs[0].text = "Section 2 header"
    doc.sections[1].footer.is_linked_to_previous = False
    doc.sections[1].footer.paragraphs[0].text = "Section 2 footer"

    specs = _docx_header_footer_specs(doc)

    kinds_and_sections = [(s[0], s[1]) for s in specs]
    assert kinds_and_sections == [("header", 0), ("header", 1), ("footer", 0), ("footer", 1)]


def test_heading_text_default_single_section():
    assert _header_footer_heading_text("header", 0, "", multi_section=False) == "Page Header"
    assert _header_footer_heading_text("footer", 0, "", multi_section=False) == "Page Footer"


def test_heading_text_default_multi_section():
    assert _header_footer_heading_text("header", 1, "", multi_section=True) == "Page Header (Section 2)"


def test_heading_text_first_page_single_section():
    assert _header_footer_heading_text("header", 0, "First Page", multi_section=False) == "Page Header (First Page)"


def test_heading_text_first_page_multi_section():
    result = _header_footer_heading_text("footer", 1, "First Page", multi_section=True)
    assert result == "Page Footer (Section 2, First Page)"


def test_heading_text_even_page_single_section():
    assert _header_footer_heading_text("header", 0, "Even Page", multi_section=False) == "Page Header (Even Page)"


def test_heading_text_even_page_multi_section():
    result = _header_footer_heading_text("header", 1, "Even Page", multi_section=True)
    assert result == "Page Header (Section 2, Even Page)"
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `backend/`): `python -m pytest tests/test_extraction.py -v`
Expected: the 12 new tests FAIL with `ImportError` (`_docx_header_footer_specs`/`_header_footer_heading_text` don't exist yet); every pre-existing test in the file still PASSES.

- [ ] **Step 3: Write the implementation**

Append to `backend/app/extraction.py` (anywhere after `_docx_paragraph_to_model` and before `extract_text`, or at the end of the file — no new imports needed, `doc.settings` and `getattr` require nothing beyond what's already imported):

```python
def _docx_header_footer_specs(doc):
    odd_even_active = doc.settings.odd_and_even_pages_header_footer
    header_specs = []
    footer_specs = []
    for section_index, section in enumerate(doc.sections):
        variants = [("header", "footer", "")]
        if section.different_first_page_header_footer:
            variants.append(("first_page_header", "first_page_footer", "First Page"))
        if odd_even_active:
            variants.append(("even_page_header", "even_page_footer", "Even Page"))
        for header_attr, footer_attr, variant_label in variants:
            header_source = getattr(section, header_attr)
            if not header_source.is_linked_to_previous:
                header_specs.append(("header", section_index, variant_label, header_source))
            footer_source = getattr(section, footer_attr)
            if not footer_source.is_linked_to_previous:
                footer_specs.append(("footer", section_index, variant_label, footer_source))
    return header_specs + footer_specs


def _header_footer_heading_text(kind, section_index, variant_label, multi_section):
    base = "Page Header" if kind == "header" else "Page Footer"
    parts = []
    if multi_section:
        parts.append(f"Section {section_index + 1}")
    if variant_label:
        parts.append(variant_label)
    if not parts:
        return base
    return f"{base} ({', '.join(parts)})"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_extraction.py -v`
Expected: PASS, all tests.

- [ ] **Step 5: Commit**

```bash
git add backend/app/extraction.py backend/tests/test_extraction.py
git commit -m "feat: add header/footer variant spec collection and heading-naming helpers"
```

---

### Task 2: Wire the helpers into extraction, replacing the combined header/footer block

**Files:**
- Modify: `backend/app/extraction.py`
- Modify: `backend/tests/test_extraction.py`

**Interfaces:**
- Consumes: `_docx_header_footer_specs`, `_header_footer_heading_text` from Task 1 (exact signatures above).
- Produces: nothing new for later tasks — this is the last task in the plan. `extract_text(file_path, "docx")`'s public return type is unchanged (`list[Paragraph]`); only the pseudo-heading text and which header/footer sources get walked changes.

- [ ] **Step 1: Write the failing tests**

First, replace one existing test that becomes stale under this change. Find in `backend/tests/test_extraction.py`:

```python
def test_extract_docx_multiple_sections_with_distinct_headers_combine(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    doc.add_paragraph("First section body.")
    doc.sections[0].header.paragraphs[0].text = "First Header"
    doc.add_section()
    # A newly added section's header defaults to is_linked_to_previous=True, in which
    # case its "paragraphs" proxy the previous section's header paragraphs (so writing
    # through it would silently overwrite "First Header" instead of creating a second,
    # distinct header). Explicitly unlink it first to get a genuinely separate header.
    doc.sections[1].header.is_linked_to_previous = False
    doc.sections[1].header.paragraphs[0].text = "Second Header"
    doc.add_paragraph("Second section body.")
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")
    texts = [p.text for p in paragraphs]

    assert "First Header" in texts
    assert "Second Header" in texts
```

Replace it with (renamed, and now proving genuine distinctness instead of just co-presence — the old name/assertions described behavior this plan deliberately changes):

```python
def test_extract_docx_multiple_sections_get_distinct_header_headings(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    doc.add_paragraph("First section body.")
    doc.sections[0].header.paragraphs[0].text = "First Header"
    doc.add_section()
    # A newly added section's header defaults to is_linked_to_previous=True, in which
    # case its "paragraphs" proxy the previous section's header paragraphs (so writing
    # through it would silently overwrite "First Header" instead of creating a second,
    # distinct header). Explicitly unlink it first to get a genuinely separate header.
    doc.sections[1].header.is_linked_to_previous = False
    doc.sections[1].header.paragraphs[0].text = "Second Header"
    doc.add_paragraph("Second section body.")
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")
    texts = [p.text for p in paragraphs]

    assert "Page Header (Section 1)" in texts
    assert "Page Header (Section 2)" in texts
    assert "Page Header" not in texts  # unqualified name must not appear once there are 2 sections

    section1_index = texts.index("Page Header (Section 1)")
    section2_index = texts.index("Page Header (Section 2)")
    assert texts[section1_index + 1] == "First Header"
    assert texts[section2_index + 1] == "Second Header"
```

Then append these new integration tests:

```python
def test_extract_docx_first_page_header_extracted_when_toggle_is_on(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    doc.add_paragraph("Body content here.")
    doc.sections[0].different_first_page_header_footer = True
    doc.sections[0].first_page_header.paragraphs[0].text = "First page header text"
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")
    texts = [p.text for p in paragraphs]

    assert "Page Header (First Page)" in texts
    assert "First page header text" in texts


def test_extract_docx_first_page_header_omitted_when_toggle_is_off(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    doc.add_paragraph("Body content here.")
    doc.sections[0].first_page_header.paragraphs[0].text = "First page header text"
    # different_first_page_header_footer deliberately left False (default) -
    # Word would never actually display this content.
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")
    texts = [p.text for p in paragraphs]

    assert "First page header text" not in texts
    assert not any("First Page" in t for t in texts)


def test_extract_docx_even_page_header_extracted_when_document_toggle_is_on(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    doc.add_paragraph("Body content here.")
    doc.settings.odd_and_even_pages_header_footer = True
    doc.sections[0].even_page_header.paragraphs[0].text = "Even page header text"
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")
    texts = [p.text for p in paragraphs]

    assert "Page Header (Even Page)" in texts
    assert "Even page header text" in texts


def test_extract_docx_even_page_header_omitted_when_document_toggle_is_off(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    doc.add_paragraph("Body content here.")
    doc.sections[0].even_page_header.paragraphs[0].text = "Even page header text"
    # doc.settings.odd_and_even_pages_header_footer deliberately left False (default).
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")
    texts = [p.text for p in paragraphs]

    assert "Even page header text" not in texts
    assert not any("Even Page" in t for t in texts)


def test_extract_docx_first_page_header_in_multi_section_document_is_fully_qualified(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    doc.add_paragraph("First section body.")
    doc.add_section()
    doc.sections[1].different_first_page_header_footer = True
    doc.sections[1].first_page_header.paragraphs[0].text = "Section 2 first page header"
    doc.add_paragraph("Second section body.")
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")
    texts = [p.text for p in paragraphs]

    assert "Page Header (Section 2, First Page)" in texts
    assert "Section 2 first page header" in texts


def test_extract_docx_first_page_header_inherited_when_linked_even_with_toggle_on(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    doc.add_paragraph("First section body.")
    doc.sections[0].different_first_page_header_footer = True
    doc.sections[0].first_page_header.paragraphs[0].text = "Section 1 first page header"
    doc.add_section()
    doc.sections[1].different_first_page_header_footer = True
    # Section 2's first_page_header is left linked to previous (default) - it should
    # inherit section 1's content rather than getting its own pseudo-section.
    doc.add_paragraph("Second section body.")
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")
    texts = [p.text for p in paragraphs]

    assert "Page Header (Section 1, First Page)" in texts
    assert "Page Header (Section 2, First Page)" not in texts


def test_extract_docx_table_inside_first_page_header_gets_table_position(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    doc.add_paragraph("Body content here.")
    doc.sections[0].different_first_page_header_footer = True
    first_page_header = doc.sections[0].first_page_header
    table = first_page_header.add_table(rows=1, cols=1, width=Inches(6))
    table.cell(0, 0).text = "First page header table cell"
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")
    cell_para = next(p for p in paragraphs if p.text == "First page header table cell")

    assert cell_para.from_table is True
    assert cell_para.table_position is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_extraction.py -v`
Expected: the rewritten `test_extract_docx_multiple_sections_get_distinct_header_headings` and the 7 new tests FAIL (heading text is still the old unqualified/combined form, first-page/even-page variants aren't extracted at all yet — `_extract_docx` doesn't call the new helpers). Every other pre-existing test still PASSES.

- [ ] **Step 3: Replace `_extract_docx`'s header/footer block**

In `backend/app/extraction.py`, find the current function (verify by reading the file first — this may have drifted):

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

    multi_section = len(doc.sections) > 1
    for kind, section_index, variant_label, source in _docx_header_footer_specs(doc):
        raw = list(_iter_docx_paragraphs(
            source.iter_inner_content(),
            allow_text_pattern_heading=False,
            table_id_counter=table_id_counter,
        ))
        # Filter out paragraphs with no real text (whitespace-only, or image/drawing-only
        # content where python-docx's Paragraph.text is empty) before checking emptiness,
        # so a header/footer with no actual content doesn't emit a bare pseudo-section.
        raw = [(p, atph, ft, tp) for p, atph, ft, tp in raw if p.text.strip()]
        if not raw:
            continue
        heading_text = _header_footer_heading_text(kind, section_index, variant_label, multi_section)
        paragraphs.append(Paragraph(text=heading_text, paragraph_index=index, is_heading=True))
        index += 1
        for para, allow_text_pattern_heading, from_table, table_position in raw:
            model = _docx_paragraph_to_model(
                para, index, baseline_pt, allow_text_pattern_heading, from_table, table_position
            )
            if model is not None:
                paragraphs.append(model)
                index += 1

    return paragraphs
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_extraction.py -v`
Expected: PASS, all tests — including the rewritten and 7 new tests from Step 1, and every pre-existing single-section header/footer test (`test_extract_docx_adds_page_header_section_when_header_is_set`, `test_extract_docx_adds_page_footer_section_when_footer_is_set`, `test_extract_docx_omits_page_header_and_footer_when_neither_is_set`, `test_extract_docx_page_header_and_footer_both_present_appear_in_order`, `test_extract_docx_whitespace_only_header_produces_no_page_header_section`, `test_extract_docx_table_inside_header_is_extracted`, `test_extract_docx_header_paragraph_not_from_table`, `test_extract_docx_table_inside_header_has_from_table_true`, `test_extract_docx_all_caps_header_text_stays_in_page_header_section`) — all single-section, default-only, must produce the exact unqualified `"Page Header"`/`"Page Footer"` text unchanged.

- [ ] **Step 5: Run the full backend suite**

Run (from `backend/`): `python -m pytest -v`
Expected: PASS, all tests, no regressions anywhere else in the suite.

- [ ] **Step 6: Commit**

```bash
git add backend/app/extraction.py backend/tests/test_extraction.py
git commit -m "feat: extract first-page/even-page header-footer variants with per-section pseudo-sections"
```
