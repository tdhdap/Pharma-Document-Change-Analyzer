# DOCX Text Box Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract text currently invisible inside Word text boxes (both modern DrawingML and legacy VML formats), since python-docx has zero API for this and a paragraph containing a text box reads as completely empty through every normal reading path.

**Architecture:** A new helper, `_iter_text_box_paragraphs`, does a raw XML search for `w:txbxContent` elements (the element both text box formats use identically to wrap their content) under a given root, yielding one group of wrapped `Paragraph` objects per text box found. `_extract_docx` calls this over the document body and every already-active header/footer source, emitting each non-empty group as its own `"Text Box N"` pseudo-section, appended after headers/footers.

**Tech Stack:** Python 3, pytest, python-docx, lxml — no new dependencies (lxml is already a python-docx dependency).

## Global Constraints

- `_iter_text_box_paragraphs(root_element, doc)` searches `root_element.findall(".//" + qn("w:txbxContent"))` (transitive — finds text boxes at any nesting depth) and yields ONE GROUP (a list of wrapped `Paragraph` objects) per text box found, not a flat stream — grouping by individual text box is required so each box gets its own pseudo-section heading.
- The same search must find BOTH modern DrawingML text boxes and legacy VML text boxes with zero format-specific branching — both wrap their content in a plain `w:txbxContent` element.
- Each raw `<w:p>` element found is wrapped via `DocxParagraph(raw_p, doc)` (using the `Document` itself as parent) so `.text`/`.style`/`.runs` all resolve correctly — this is how `_iter_text_box_paragraphs` produces real python-docx `Paragraph` objects usable with the existing `_docx_paragraph_to_model` conversion.
- Scope: whole document (body + every already-active header/footer variant returned by the existing `_docx_header_footer_specs(doc)` — reused directly, not re-derived).
- Representation: `"Text Box {n}"` (1-indexed, single global counter across the whole document, no location qualifier).
- Placement: appended to the paragraph stream after headers/footers.
- `from_table` and `table_position` stay at their defaults (`False`/`None`) for all text box content, always — never passed as kwargs to `_docx_paragraph_to_model` for this content.
- `allow_text_pattern_heading=False` for text box paragraph conversion (same reasoning already applied to tables/headers/footers — short captions/labels inside a text box look like headings by shape alone).
- An empty text box (no real text in any of its paragraphs) produces no pseudo-section at all — same whitespace-only-content guard already used for headers/footers.
- Reference: `docs/superpowers/specs/2026-08-15-docx-textbox-extraction-design.md`.

---

### Task 1: Add the text box search helper

**Files:**
- Modify: `backend/app/extraction.py`
- Modify: `backend/tests/test_extraction.py`

**Interfaces:**
- Produces: `_iter_text_box_paragraphs(root_element, doc) -> Iterator[list[DocxParagraph]]` in `app/extraction.py`. Consumed by Task 2.

- [ ] **Step 1: Write the failing tests**

At the top of `backend/tests/test_extraction.py`, add these imports (check the file's existing import block first — it currently starts with `import fitz`, `from docx import Document as DocxDocument`, `from docx.shared import Inches, Pt`, `from app.extraction import extract_text`, `from app.sectioning import split_into_sections`; add these alongside, don't remove any existing ones):

```python
from lxml import etree
from docx.oxml.ns import qn
from app.extraction import _iter_text_box_paragraphs
```

Then append these module-level test helpers (used by every test in this task and Task 2 — this constructs real text box XML directly via lxml, since python-docx has no API to add one):

```python
_DRAWINGML_TEXTBOX_XML = """<w:drawing xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
    xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
    xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape">
  <wp:inline>
    <wp:extent cx="1828800" cy="1143000"/>
    <a:graphic>
      <a:graphicData uri="http://schemas.microsoft.com/office/word/2010/wordprocessingShape">
        <wps:wsp>
          <wps:txbx>
            <w:txbxContent>{paragraphs}</w:txbxContent>
          </wps:txbx>
        </wps:wsp>
      </a:graphicData>
    </a:graphic>
  </wp:inline>
</w:drawing>"""

_VML_TEXTBOX_XML = """<w:pict xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    xmlns:v="urn:schemas-microsoft-com:vml"
    xmlns:o="urn:schemas-microsoft-com:office:office">
  <v:shape style="width:150pt;height:80pt">
    <v:textbox>
      <w:txbxContent>{paragraphs}</w:txbxContent>
    </v:textbox>
  </v:shape>
</w:pict>"""


def _paragraph_xml(*run_texts):
    runs = "".join(f'<w:r><w:t xml:space="preserve">{t}</w:t></w:r>' for t in run_texts)
    return f"<w:p>{runs}</w:p>"


def _add_text_box(container_element, paragraph_texts, vml=False):
    """Inject a real text box (DrawingML by default, VML if vml=True) containing the
    given paragraphs into container_element (e.g. doc.element.body, a table cell's
    _tc, or a header/footer's _element - any lxml element works generically).
    python-docx has no API to add a text box, so this constructs the raw OOXML
    directly - the exact technique verified empirically before writing this plan."""
    p = container_element.makeelement(qn("w:p"), {})
    r = p.makeelement(qn("w:r"), {})
    p.append(r)
    paragraphs_xml = "".join(_paragraph_xml(text) for text in paragraph_texts)
    template = _VML_TEXTBOX_XML if vml else _DRAWINGML_TEXTBOX_XML
    drawing = etree.fromstring(template.format(paragraphs=paragraphs_xml).encode())
    r.append(drawing)
    container_element.append(p)
```

Then append these test functions:

```python
def test_iter_text_box_paragraphs_finds_drawingml_text_box():
    doc = DocxDocument()
    _add_text_box(doc.element.body, ["Text box paragraph one.", "Text box paragraph two."])

    groups = list(_iter_text_box_paragraphs(doc.element.body, doc))

    assert len(groups) == 1
    assert [p.text for p in groups[0]] == ["Text box paragraph one.", "Text box paragraph two."]


def test_iter_text_box_paragraphs_finds_vml_text_box():
    doc = DocxDocument()
    _add_text_box(doc.element.body, ["Legacy VML text box paragraph."], vml=True)

    groups = list(_iter_text_box_paragraphs(doc.element.body, doc))

    assert len(groups) == 1
    assert [p.text for p in groups[0]] == ["Legacy VML text box paragraph."]


def test_iter_text_box_paragraphs_joins_multiple_runs():
    doc = DocxDocument()
    p = doc.element.body.makeelement(qn("w:p"), {})
    r = p.makeelement(qn("w:r"), {})
    p.append(r)
    paragraphs_xml = _paragraph_xml("Multi-", "run", " sentence.")
    drawing = etree.fromstring(_DRAWINGML_TEXTBOX_XML.format(paragraphs=paragraphs_xml).encode())
    r.append(drawing)
    doc.element.body.append(p)

    groups = list(_iter_text_box_paragraphs(doc.element.body, doc))

    assert len(groups) == 1
    assert [p.text for p in groups[0]] == ["Multi-run sentence."]


def test_iter_text_box_paragraphs_returns_nothing_when_none_present():
    doc = DocxDocument()
    doc.add_paragraph("Ordinary paragraph, no text box.")

    groups = list(_iter_text_box_paragraphs(doc.element.body, doc))

    assert groups == []


def test_iter_text_box_paragraphs_finds_multiple_text_boxes_as_separate_groups():
    doc = DocxDocument()
    _add_text_box(doc.element.body, ["First box text."])
    _add_text_box(doc.element.body, ["Second box text."])

    groups = list(_iter_text_box_paragraphs(doc.element.body, doc))

    assert len(groups) == 2
    assert [p.text for p in groups[0]] == ["First box text."]
    assert [p.text for p in groups[1]] == ["Second box text."]


def test_iter_text_box_paragraphs_finds_text_box_inside_table_cell():
    doc = DocxDocument()
    table = doc.add_table(rows=1, cols=1)
    cell_element = table.cell(0, 0)._tc
    _add_text_box(cell_element, ["Table cell text box."])

    groups = list(_iter_text_box_paragraphs(doc.element.body, doc))

    assert len(groups) == 1
    assert [p.text for p in groups[0]] == ["Table cell text box."]


def test_iter_text_box_paragraphs_handles_nested_text_box_as_separate_group():
    doc = DocxDocument()
    p = doc.element.body.makeelement(qn("w:p"), {})
    r = p.makeelement(qn("w:r"), {})
    p.append(r)
    inner_paragraphs_xml = _paragraph_xml("Inner nested box text.")
    inner_drawing_xml = _DRAWINGML_TEXTBOX_XML.format(paragraphs=inner_paragraphs_xml)
    outer_paragraphs_xml = (
        '<w:p><w:r><w:t xml:space="preserve">Outer box own text.</w:t></w:r>'
        f'<w:r>{inner_drawing_xml}</w:r></w:p>'
    )
    outer_drawing = etree.fromstring(_DRAWINGML_TEXTBOX_XML.format(paragraphs=outer_paragraphs_xml).encode())
    r.append(outer_drawing)
    doc.element.body.append(p)

    groups = list(_iter_text_box_paragraphs(doc.element.body, doc))

    assert len(groups) == 2
    assert [p.text for p in groups[0]] == ["Outer box own text."]
    assert [p.text for p in groups[1]] == ["Inner nested box text."]
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `backend/`): `python -m pytest tests/test_extraction.py -v`
Expected: the 7 new tests FAIL with `ImportError` (`_iter_text_box_paragraphs` doesn't exist yet). Every pre-existing test in the file still PASSES.

- [ ] **Step 3: Add the required imports to extraction.py**

At the top of `backend/app/extraction.py`, find:

```python
import collections
import itertools

import fitz
from docx import Document as DocxDocument
from docx.table import Table as DocxTable
from docx.text.paragraph import Paragraph as DocxParagraph
```

Replace with:

```python
import collections
import itertools

import fitz
from docx import Document as DocxDocument
from docx.oxml.ns import qn
from docx.table import Table as DocxTable
from docx.text.paragraph import Paragraph as DocxParagraph
```

- [ ] **Step 4: Write the implementation**

Append to `backend/app/extraction.py` (anywhere after `_docx_paragraph_to_model` and before `extract_text`, or at the end of the file — no new imports beyond `qn`, already added in Step 3):

```python
def _iter_text_box_paragraphs(root_element, doc):
    # python-docx has no API for text boxes at all - a paragraph containing one
    # reads as completely empty through every normal reading path (verified
    # empirically before writing this plan). Both text box formats Word uses -
    # modern DrawingML and legacy VML - wrap their actual content in a plain
    # w:txbxContent element, so this single search finds both identically with
    # no format-specific branching. The search is transitive (".//"), so it finds
    # text boxes at any nesting depth - inside table cells, inside other text
    # boxes, etc. - with no special recursion needed, unlike table extraction.
    for txbx in root_element.findall(".//" + qn("w:txbxContent")):
        yield [DocxParagraph(raw_p, doc) for raw_p in txbx.findall(qn("w:p"))]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_extraction.py -v`
Expected: PASS, all tests.

- [ ] **Step 6: Commit**

```bash
git add backend/app/extraction.py backend/tests/test_extraction.py
git commit -m "feat: add text box search helper for DOCX extraction"
```

---

### Task 2: Wire text box extraction into _extract_docx

**Files:**
- Modify: `backend/app/extraction.py`
- Modify: `backend/tests/test_extraction.py`

**Interfaces:**
- Consumes: `_iter_text_box_paragraphs` from Task 1 (exact signature above).
- Produces: nothing new for later tasks — `extract_text(file_path, "docx")`'s public return type is unchanged (`list[Paragraph]`); it now additionally includes `"Text Box N"` pseudo-sections when the document contains any.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_extraction.py` (reuses `_add_text_box` from Task 1, already in this file):

```python
def test_extract_docx_text_box_in_body_is_extracted(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    doc.add_paragraph("Normal body paragraph.")
    _add_text_box(doc.element.body, ["Text box content here."])
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")
    texts = [p.text for p in paragraphs]

    assert "Text Box 1" in texts
    text_box_index = texts.index("Text Box 1")
    assert paragraphs[text_box_index].is_heading is True
    assert "Text box content here." in texts


def test_extract_docx_text_box_content_has_correct_default_fields(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    _add_text_box(doc.element.body, ["Text box content here."])
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")
    content_para = next(p for p in paragraphs if p.text == "Text box content here.")

    assert content_para.from_table is False
    assert content_para.table_position is None


def test_extract_docx_multiple_text_boxes_get_sequential_numbers(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    _add_text_box(doc.element.body, ["First box."])
    _add_text_box(doc.element.body, ["Second box."])
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")
    texts = [p.text for p in paragraphs]

    assert "Text Box 1" in texts
    assert "Text Box 2" in texts
    assert texts.index("Text Box 1") < texts.index("First box.")
    assert texts.index("Text Box 2") < texts.index("Second box.")


def test_extract_docx_empty_text_box_produces_no_pseudo_section(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    doc.add_paragraph("Normal body paragraph.")
    _add_text_box(doc.element.body, [""])
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")
    texts = [p.text for p in paragraphs]

    assert "Text Box 1" not in texts


def test_extract_docx_text_box_inside_active_first_page_header_is_extracted(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    doc.add_paragraph("Body content here.")
    doc.sections[0].different_first_page_header_footer = True
    first_page_header_element = doc.sections[0].first_page_header._element
    _add_text_box(first_page_header_element, ["First page header text box."])
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")
    texts = [p.text for p in paragraphs]

    assert "Text Box 1" in texts
    assert "First page header text box." in texts


def test_extract_docx_text_box_inside_inactive_variant_is_not_extracted(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    doc.add_paragraph("Body content here.")
    # different_first_page_header_footer deliberately left False - Word would never
    # display this content, and _docx_header_footer_specs correctly excludes this
    # variant entirely regardless of the text box injected into it.
    first_page_header_element = doc.sections[0].first_page_header._element
    _add_text_box(first_page_header_element, ["Inactive first page header text box."])
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")
    texts = [p.text for p in paragraphs]

    assert "Inactive first page header text box." not in texts
    assert "Text Box 1" not in texts


def test_extract_docx_without_text_boxes_is_unchanged(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    doc.add_paragraph("1.0 Scope", style="Heading 1")
    doc.add_paragraph("This procedure applies to all testing.")
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")

    assert len(paragraphs) == 2
    assert paragraphs[0].text == "1.0 Scope"
    assert paragraphs[1].text == "This procedure applies to all testing."
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_extraction.py -v`
Expected: the first 6 new tests FAIL (no `"Text Box N"` pseudo-sections are produced yet — `_extract_docx` doesn't call `_iter_text_box_paragraphs` yet). `test_extract_docx_without_text_boxes_is_unchanged` PASSES already (nothing about this feature affects a document with no text boxes, until the feature exists — this is here as a named regression guard for the next step, not to prove a fix). Every pre-existing test in the file still PASSES.

- [ ] **Step 3: Add the text box extraction block to _extract_docx**

In `backend/app/extraction.py`, find the end of `_extract_docx` (verify by reading the file first — this may have drifted):

```python
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

Replace it with (adds the new block, ending the function the same way as before):

```python
    multi_section = len(doc.sections) > 1
    header_footer_specs = _docx_header_footer_specs(doc)
    for kind, section_index, variant_label, source in header_footer_specs:
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

    text_box_roots = [doc.element.body] + [source._element for _, _, _, source in header_footer_specs]
    text_box_number = 0
    for root_element in text_box_roots:
        for group in _iter_text_box_paragraphs(root_element, doc):
            group = [p for p in group if p.text.strip()]
            if not group:
                continue
            text_box_number += 1
            paragraphs.append(Paragraph(text=f"Text Box {text_box_number}", paragraph_index=index, is_heading=True))
            index += 1
            for para in group:
                model = _docx_paragraph_to_model(para, index, baseline_pt, allow_text_pattern_heading=False)
                if model is not None:
                    paragraphs.append(model)
                    index += 1

    return paragraphs
```

(The only change to the existing header/footer block is capturing its `_docx_header_footer_specs(doc)` call into a local variable, `header_footer_specs`, so the new text-box block can reuse the same already-computed specs instead of calling that function twice — everything else in that block is untouched. `_docx_paragraph_to_model` is called here with only 3 positional args plus the keyword `allow_text_pattern_heading=False` — `from_table` and `table_position` are deliberately omitted so they take their `False`/`None` defaults.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_extraction.py -v`
Expected: PASS, all tests — the 6 new tests from Step 1, `test_extract_docx_without_text_boxes_is_unchanged`, and every pre-existing test in the file (in particular every table/header/footer test already in this file — none of them involve text boxes, so none of their expected output changes).

- [ ] **Step 5: Run the full backend suite**

Run (from `backend/`): `python -m pytest -v`
Expected: PASS, all tests, no regressions anywhere else in the suite (nothing downstream of extraction has ever seen a `"Text Box N"` heading before, but nothing needs to specifically recognize it either — it flows through the exact same generic `Section.heading` path every other pseudo-section already does).

- [ ] **Step 6: Commit**

```bash
git add backend/app/extraction.py backend/tests/test_extraction.py
git commit -m "feat: extract text box content as Text Box N pseudo-sections"
```
