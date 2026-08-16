# DOCX Footnote Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract Word footnote content (from the separate `word/footnotes.xml` OOXML part) into the paragraph stream as `"Footnote N"` pseudo-sections, so footnote changes are no longer invisible to document comparison.

**Architecture:** Two new helpers in `backend/app/extraction.py` discover the footnotes part (via relationship type, not content-type sniffing) and map each real footnote's `w:id` to its extracted paragraph content (reusing the existing table-aware content walk already built for text boxes). `_extract_docx` is extended to collect footnote reference ids during its existing body walk (no second walk), then append each referenced footnote's content as a `"Footnote N"` pseudo-section, in reference order, after text boxes. `section_structure.py` gains a heading-shape exclusion for `"Footnote N"` so renumbering (an earlier footnote being added/removed) can never spuriously flag a later, unchanged footnote — built in now, not discovered later by a whole-branch review.

**Tech Stack:** Python, FastAPI backend, python-docx, lxml (via `docx.oxml.parse_xml`), pytest.

## Global Constraints

- Extraction only — no persistence/export/frontend changes, no new `Change` fields. (spec: "Decision")
- Footnotes part discovered via `doc.part.rels`, filtering `reltype == "http://schemas.openxmlformats.org/officeDocument/2006/relationships/footnotes"` — never content-type string matching. (spec: "Discovery via relationship type")
- Footnote content parsed via `docx.oxml.parse_xml(rel.target_part.blob)`, never `lxml.etree.fromstring`, for the footnotes part itself. (spec: "Parsing via docx.oxml.parse_xml")
- Exclude footnotes whose `w:type` is `"separator"` or `"continuationSeparator"` — these are Word-internal print-layout boilerplate, never real content. (spec: "Filtering out Word-internal boilerplate footnotes")
- Naming: `"Footnote {n}"`, 1-indexed, one global sequential counter, in **document reference order** (the order `<w:footnoteReference>` elements are encountered while walking the body) — **not** `w:id` order, which the OOXML spec does not guarantee matches reference order. (spec: "Ordering and naming")
- Placement: all footnote pseudo-sections appended at the very end of the returned paragraph list, after text boxes. (spec: "Ordering and naming")
- Footnote content always gets `allow_text_pattern_heading=False`, `from_table=False`, `table_position=None`, regardless of whether the footnote's own body contains a table. (spec: "Nested content")
- `detect_section_heading_changed` must skip any comparison where either heading matches `"Footnote N"` — added as a new, independent check, never folded into the shared `is_synthetic_heading` (which also gates `detect_section_added`/`_deleted`/`_reordered`, and must keep firing correctly for a genuinely added/removed/reordered footnote). (spec: "Renumbering-safety")
- Out of scope: endnotes, inline/positional placement, any new comparison logic beyond the renumbering guard, PDF/TXT. (spec: "Out of Scope")

---

### Task 1: Footnote discovery and content-extraction helpers

**Files:**
- Modify: `backend/app/extraction.py`
- Test: `backend/tests/test_extraction.py`

**Interfaces:**
- Consumes: `_iter_docx_paragraphs` (existing, `backend/app/extraction.py:81`) — unchanged signature, `(content_iter, allow_text_pattern_heading=True, table_id_counter=None) -> Iterator[tuple[DocxParagraph, bool, bool, TableCoordinate | None]]`.
- Produces:
  - `_content_iter(element, doc) -> Iterator[DocxParagraph | DocxTable]` — renamed from `_txbx_content_iter` (was text-box-specific in name only; behavior is generic and this task reuses it for footnotes).
  - `_footnotes_root(doc) -> lxml.etree._Element | None` — the parsed `<w:footnotes>` root, or `None` if the document has no footnotes part.
  - `_footnote_content_by_id(footnotes_root, doc) -> dict[str, list[DocxParagraph]]` — maps each real (non-boilerplate) footnote's `w:id` string to its list of extracted `DocxParagraph` objects. Consumed by Task 2.

This task does **not** wire footnote content into `_extract_docx` yet — these two helpers are tested standalone. Wiring happens in Task 2.

- [ ] **Step 1: Rename `_txbx_content_iter` to `_content_iter`**

In `backend/app/extraction.py`, find:

```python
def _txbx_content_iter(txbx_element, doc):
    for child in txbx_element:
        if child.tag == qn("w:p"):
            yield DocxParagraph(child, doc)
        elif child.tag == qn("w:tbl"):
            yield DocxTable(child, doc)
```

Replace with:

```python
def _content_iter(element, doc):
    for child in element:
        if child.tag == qn("w:p"):
            yield DocxParagraph(child, doc)
        elif child.tag == qn("w:tbl"):
            yield DocxTable(child, doc)
```

Then find its one call site, inside `_iter_text_box_paragraphs`:

```python
        yield [para for para, _, _, _ in _iter_docx_paragraphs(_txbx_content_iter(txbx, doc))]
```

Replace with:

```python
        yield [para for para, _, _, _ in _iter_docx_paragraphs(_content_iter(txbx, doc))]
```

- [ ] **Step 2: Run the full backend suite to confirm the rename didn't break anything**

Run: `cd backend && python -m pytest -q`
Expected: all tests pass (238 passed), identical to before the rename — this is a pure rename with no behavior change.

- [ ] **Step 3: Add `import` for `parse_xml`**

In `backend/app/extraction.py`, find:

```python
from docx import Document as DocxDocument
from docx.oxml.ns import qn
```

Replace with:

```python
from docx import Document as DocxDocument
from docx.oxml import parse_xml
from docx.oxml.ns import qn
```

- [ ] **Step 4: Write the failing tests for `_footnotes_root`**

In `backend/tests/test_extraction.py`, add to the imports at the top:

```python
from app.extraction import _footnotes_root, _footnote_content_by_id
```

(this becomes a second line alongside the existing `from app.extraction import _iter_text_box_paragraphs` — do not merge them into one import statement, matching the file's existing style of one `from app.extraction import ...` line per feature area).

Add these tests (append to the end of the file):

```python
def test_footnotes_root_returns_none_when_document_has_no_footnotes():
    doc = DocxDocument()
    doc.add_paragraph("Plain paragraph, no footnotes.")

    assert _footnotes_root(doc) is None
```

```python
def test_footnote_content_by_id_excludes_boilerplate_and_keys_by_id():
    footnotes_xml = (
        '<w:footnotes xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:footnote w:type="separator" w:id="-1"><w:p><w:r><w:separator/></w:r></w:p></w:footnote>'
        '<w:footnote w:type="continuationSeparator" w:id="0">'
        '<w:p><w:r><w:continuationSeparator/></w:r></w:p></w:footnote>'
        '<w:footnote w:id="1">' + _paragraph_xml("See ICH Q1A(R2) for stability testing requirements.") + '</w:footnote>'
        '</w:footnotes>'
    )
    root = parse_xml(footnotes_xml.encode())
    doc = DocxDocument()

    content_by_id = _footnote_content_by_id(root, doc)

    assert list(content_by_id.keys()) == ["1"]
    assert [para.text for para in content_by_id["1"]] == ["See ICH Q1A(R2) for stability testing requirements."]
```

```python
def test_footnote_content_by_id_extracts_multi_paragraph_footnote():
    footnotes_xml = (
        '<w:footnotes xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:footnote w:id="1">'
        + _paragraph_xml("First line of the footnote.")
        + _paragraph_xml("Second line of the footnote.")
        + '</w:footnote>'
        '</w:footnotes>'
    )
    root = parse_xml(footnotes_xml.encode())
    doc = DocxDocument()

    content_by_id = _footnote_content_by_id(root, doc)

    assert [para.text for para in content_by_id["1"]] == [
        "First line of the footnote.", "Second line of the footnote.",
    ]
```

```python
def test_footnote_content_by_id_extracts_nested_table_content():
    footnotes_xml = (
        '<w:footnotes xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:footnote w:id="1">'
        '<w:p><w:r><w:t xml:space="preserve">Reference standards:</w:t></w:r></w:p>'
        '<w:tbl>'
        '<w:tblPr/><w:tblGrid><w:gridCol/><w:gridCol/></w:tblGrid>'
        '<w:tr>'
        '<w:tc><w:p><w:r><w:t xml:space="preserve">USP</w:t></w:r></w:p></w:tc>'
        '<w:tc><w:p><w:r><w:t xml:space="preserve">Chapter 621</w:t></w:r></w:p></w:tc>'
        '</w:tr>'
        '</w:tbl>'
        '</w:footnote>'
        '</w:footnotes>'
    )
    root = parse_xml(footnotes_xml.encode())
    doc = DocxDocument()

    content_by_id = _footnote_content_by_id(root, doc)

    assert [para.text for para in content_by_id["1"]] == ["Reference standards:", "USP", "Chapter 621"]
```

```python
def test_footnote_content_by_id_handles_multiple_non_contiguous_ids():
    footnotes_xml = (
        '<w:footnotes xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:footnote w:id="5">' + _paragraph_xml("First citation text.") + '</w:footnote>'
        '<w:footnote w:id="7">' + _paragraph_xml("Second citation text.") + '</w:footnote>'
        '</w:footnotes>'
    )
    root = parse_xml(footnotes_xml.encode())
    doc = DocxDocument()

    content_by_id = _footnote_content_by_id(root, doc)

    assert set(content_by_id.keys()) == {"5", "7"}
    assert [para.text for para in content_by_id["5"]] == ["First citation text."]
    assert [para.text for para in content_by_id["7"]] == ["Second citation text."]
```

- [ ] **Step 5: Run the tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_extraction.py -k footnote -v`
Expected: FAIL with `ImportError: cannot import name '_footnotes_root'` (the functions don't exist yet).

- [ ] **Step 6: Implement `_footnotes_root` and `_footnote_content_by_id`**

In `backend/app/extraction.py`, find the end of `_iter_text_box_paragraphs` (the function ends with the line below) and the following `_docx_header_footer_specs` definition:

```python
    for txbx in root_element.findall(".//" + qn("w:txbxContent")):
        if _has_mc_fallback_ancestor(txbx):
            continue
        yield [para for para, _, _, _ in _iter_docx_paragraphs(_content_iter(txbx, doc))]


def _docx_header_footer_specs(doc) -> list[tuple[str, int, str, object]]:
```

Insert the two new functions between them, so the file reads:

```python
    for txbx in root_element.findall(".//" + qn("w:txbxContent")):
        if _has_mc_fallback_ancestor(txbx):
            continue
        yield [para for para, _, _, _ in _iter_docx_paragraphs(_content_iter(txbx, doc))]


_FOOTNOTES_RELTYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/footnotes"
_EXCLUDED_FOOTNOTE_TYPES = {"separator", "continuationSeparator"}


def _footnotes_root(doc):
    # python-docx has no API for footnotes at all - the footnotes part loads as an
    # opaque, unparsed Part (verified empirically: it has no registered subclass for
    # the footnotes content type, so python-docx exposes only a raw .blob). The
    # relationship type is the canonical, stable way to locate it regardless of that -
    # verified empirically to be present and correctly typed even though the part
    # itself is otherwise unrecognized, and cleanly absent (no error) on documents
    # with no footnotes.
    for rel in doc.part.rels.values():
        if rel.reltype == _FOOTNOTES_RELTYPE:
            return parse_xml(rel.target_part.blob)
    return None


def _footnote_content_by_id(footnotes_root, doc):
    # Word writes two non-content footnotes used purely for print layout - a
    # "separator" and a "continuationSeparator" - identified by w:type. Real,
    # user-authored footnotes have no w:type attribute (or, per the OOXML spec's
    # allowance, an explicit w:type="normal") - both are treated as real content.
    # Keyed by w:id (a string, not necessarily contiguous or in document order) -
    # verified empirically that Word does not guarantee footnote ids are assigned
    # in reference order, so callers must join on this id, never on position.
    #
    # A footnote's content model allows both paragraphs and tables (the same content
    # model already handled for text boxes) - reusing _content_iter + _iter_docx_paragraphs
    # here means a table inside a footnote is captured correctly from the start,
    # rather than needing a second fix later the way text boxes did.
    content_by_id = {}
    for footnote in footnotes_root.findall(qn("w:footnote")):
        if footnote.get(qn("w:type")) in _EXCLUDED_FOOTNOTE_TYPES:
            continue
        footnote_id = footnote.get(qn("w:id"))
        content_by_id[footnote_id] = [
            para for para, _, _, _ in _iter_docx_paragraphs(_content_iter(footnote, doc))
        ]
    return content_by_id


def _docx_header_footer_specs(doc) -> list[tuple[str, int, str, object]]:
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_extraction.py -k footnote -v`
Expected: 5 passed (`test_footnotes_root_returns_none_when_document_has_no_footnotes`, `test_footnote_content_by_id_excludes_boilerplate_and_keys_by_id`, `test_footnote_content_by_id_extracts_multi_paragraph_footnote`, `test_footnote_content_by_id_extracts_nested_table_content`, `test_footnote_content_by_id_handles_multiple_non_contiguous_ids`).

- [ ] **Step 8: Run the full backend suite**

Run: `cd backend && python -m pytest -q`
Expected: all tests pass (243 passed — 238 existing + 5 new).

- [ ] **Step 9: Commit**

```bash
git add backend/app/extraction.py backend/tests/test_extraction.py
git commit -m "feat: add footnote discovery and content-extraction helpers"
```

---

### Task 2: Wire footnote extraction into `_extract_docx` and add renumbering-safety guard

**Files:**
- Modify: `backend/app/extraction.py`
- Modify: `backend/app/section_structure.py`
- Test: `backend/tests/test_extraction.py`
- Test: `backend/tests/test_section_structure.py`
- Test: `backend/tests/test_pipeline.py`

**Interfaces:**
- Consumes: `_footnotes_root(doc)` and `_footnote_content_by_id(footnotes_root, doc)` from Task 1 (`backend/app/extraction.py`).
- Consumes: `_is_page_header_or_footer_heading`, `_is_text_box_heading` (existing, `backend/app/section_structure.py:77-85`) — pattern to mirror, not called directly.
- Produces: `_is_footnote_heading(heading: str) -> bool` (`backend/app/section_structure.py`) — a new exclusion check wired into `detect_section_heading_changed`.
- Produces: `_extract_docx` now includes `"Footnote N"` pseudo-sections in its output for any DOCX with footnote references — this is the end-to-end, user-visible deliverable of this plan.

This task requires building a real DOCX with a genuine `word/footnotes.xml` part for testing. Because python-docx exposes no API to add this part, test fixtures manipulate the saved `.docx` zip package directly (add the part, its content-type override, and its relationship) — the same class of technique already used for text boxes, but at the OPC package level instead of inline XML, since footnotes live in a wholly separate part. This exact technique was verified end-to-end (built, saved, reopened, and extracted correctly, including non-contiguous footnote ids) before this plan was written.

- [ ] **Step 1: Add the footnote test-fixture helpers to `test_extraction.py`**

In `backend/tests/test_extraction.py`, append these two helpers (after the existing `_add_text_box` helper, before the first test function that will use them):

```python
def _add_footnote_reference(paragraph, footnote_id):
    """Inject a real <w:footnoteReference w:id="..."/> into the given python-docx
    Paragraph's XML - python-docx has no API to add a footnote reference, so this
    constructs the raw OOXML directly, the same technique already used for text boxes."""
    p = paragraph._p
    r = p.makeelement(qn("w:r"), {})
    ref = r.makeelement(qn("w:footnoteReference"), {qn("w:id"): str(footnote_id)})
    r.append(ref)
    p.append(r)


def _save_docx_with_footnotes(doc, path, footnotes):
    """Save doc, then splice a real word/footnotes.xml part into the resulting .docx
    package (content-type override + relationship + the part itself). python-docx has
    no API to add this part, so this manipulates the OPC zip package directly - the
    exact technique verified empirically before writing this plan. `footnotes` is a
    list of (footnote_id, paragraph_texts) tuples for the real (non-boilerplate)
    footnotes; the two Word-internal separator footnotes are always included. Callers
    must have already used _add_footnote_reference for each corresponding id before
    calling doc.save() - this only splices the footnotes.xml part and its relationship,
    not the body's own <w:footnoteReference> elements."""
    doc.save(path)
    footnote_blocks = "".join(
        f'<w:footnote w:id="{fid}">' + "".join(_paragraph_xml(t) for t in texts) + "</w:footnote>"
        for fid, texts in footnotes
    )
    footnotes_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:footnotes xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:footnote w:type="separator" w:id="-1"><w:p><w:r><w:separator/></w:r></w:p></w:footnote>'
        '<w:footnote w:type="continuationSeparator" w:id="0">'
        '<w:p><w:r><w:continuationSeparator/></w:r></w:p></w:footnote>'
        f'{footnote_blocks}'
        '</w:footnotes>'
    )
    with zipfile.ZipFile(path, "r") as zin:
        names = zin.namelist()
        content_types_xml = zin.read("[Content_Types].xml").decode("utf-8")
        rels_xml = zin.read("word/_rels/document.xml.rels").decode("utf-8")
        other = {n: zin.read(n) for n in names if n not in ("[Content_Types].xml", "word/_rels/document.xml.rels")}

    content_types_xml = content_types_xml.replace(
        "</Types>",
        '<Override PartName="/word/footnotes.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml"/></Types>',
    )
    rels_xml = rels_xml.replace(
        "</Relationships>",
        '<Relationship Id="rIdFootnotes" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footnotes" '
        'Target="footnotes.xml"/></Relationships>',
    )

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zout:
        zout.writestr("[Content_Types].xml", content_types_xml)
        zout.writestr("word/_rels/document.xml.rels", rels_xml)
        zout.writestr("word/footnotes.xml", footnotes_xml)
        for name, data in other.items():
            zout.writestr(name, data)
```

Add `import zipfile` and `import tempfile`, `import os` at the top of the file (`tempfile`/`os` are needed because these tests save to a real temp path, unlike this file's existing tests which mostly use pytest's `tmp_path` fixture directly — using `tmp_path` here is fine too; use whichever this file's existing DOCX-saving tests already use — check the top of `test_extraction.py`, e.g. `test_extract_docx_reads_paragraphs(tmp_path)`, and follow that exact convention with `tmp_path` instead of `tempfile.TemporaryDirectory()`):

```python
import zipfile
```

(add this single line to the existing import block; `tmp_path` is a built-in pytest fixture requiring no import).

- [ ] **Step 2: Write the failing tests for full `extract_text` round-trip**

Append to `backend/tests/test_extraction.py`:

```python
def test_extract_docx_single_footnote_is_extracted(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    p = doc.add_paragraph("This is a claim with a footnote reference.")
    _add_footnote_reference(p, "1")
    _save_docx_with_footnotes(doc, str(file_path), [("1", ["See ICH Q1A(R2) for stability testing requirements."])])

    paragraphs = extract_text(str(file_path), "docx")

    texts = [par.text for par in paragraphs]
    assert texts == [
        "This is a claim with a footnote reference.",
        "Footnote 1",
        "See ICH Q1A(R2) for stability testing requirements.",
    ]
    heading_flags = {par.text: par.is_heading for par in paragraphs}
    assert heading_flags["Footnote 1"] is True
    assert heading_flags["See ICH Q1A(R2) for stability testing requirements."] is False


def test_extract_docx_multiple_footnotes_get_sequential_numbers_in_reference_order(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    p1 = doc.add_paragraph("First claim.")
    _add_footnote_reference(p1, "5")
    p2 = doc.add_paragraph("Second claim.")
    _add_footnote_reference(p2, "7")
    _save_docx_with_footnotes(doc, str(file_path), [
        ("5", ["First citation text."]),
        ("7", ["Second citation text."]),
    ])

    paragraphs = extract_text(str(file_path), "docx")

    texts = [par.text for par in paragraphs]
    assert texts == [
        "First claim.", "Second claim.",
        "Footnote 1", "First citation text.",
        "Footnote 2", "Second citation text.",
    ]


def test_extract_docx_footnote_content_has_correct_default_fields(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    p = doc.add_paragraph("Claim.")
    _add_footnote_reference(p, "1")
    _save_docx_with_footnotes(doc, str(file_path), [("1", ["Citation text."])])

    paragraphs = extract_text(str(file_path), "docx")

    footnote_para = next(par for par in paragraphs if par.text == "Citation text.")
    assert footnote_para.from_table is False
    assert footnote_para.table_position is None
    assert footnote_para.allow_text_pattern_heading is False


def test_extract_docx_footnote_with_nested_table_is_extracted(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    p = doc.add_paragraph("Claim needing a reference standard.")
    _add_footnote_reference(p, "1")
    doc.save(str(file_path))
    footnotes_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:footnotes xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:footnote w:id="1">'
        '<w:p><w:r><w:t xml:space="preserve">Reference standards:</w:t></w:r></w:p>'
        '<w:tbl>'
        '<w:tblPr/><w:tblGrid><w:gridCol/><w:gridCol/></w:tblGrid>'
        '<w:tr>'
        '<w:tc><w:p><w:r><w:t xml:space="preserve">USP</w:t></w:r></w:p></w:tc>'
        '<w:tc><w:p><w:r><w:t xml:space="preserve">Chapter 621</w:t></w:r></w:p></w:tc>'
        '</w:tr>'
        '</w:tbl>'
        '</w:footnote>'
        '</w:footnotes>'
    )
    with zipfile.ZipFile(str(file_path), "r") as zin:
        names = zin.namelist()
        content_types_xml = zin.read("[Content_Types].xml").decode("utf-8")
        rels_xml = zin.read("word/_rels/document.xml.rels").decode("utf-8")
        other = {n: zin.read(n) for n in names if n not in ("[Content_Types].xml", "word/_rels/document.xml.rels")}
    content_types_xml = content_types_xml.replace(
        "</Types>",
        '<Override PartName="/word/footnotes.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml"/></Types>',
    )
    rels_xml = rels_xml.replace(
        "</Relationships>",
        '<Relationship Id="rIdFootnotes" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footnotes" '
        'Target="footnotes.xml"/></Relationships>',
    )
    with zipfile.ZipFile(str(file_path), "w", zipfile.ZIP_DEFLATED) as zout:
        zout.writestr("[Content_Types].xml", content_types_xml)
        zout.writestr("word/_rels/document.xml.rels", rels_xml)
        zout.writestr("word/footnotes.xml", footnotes_xml)
        for name, data in other.items():
            zout.writestr(name, data)

    paragraphs = extract_text(str(file_path), "docx")

    texts = [par.text for par in paragraphs]
    assert texts == [
        "Claim needing a reference standard.",
        "Footnote 1", "Reference standards:", "USP", "Chapter 621",
    ]
    table_para = next(par for par in paragraphs if par.text == "USP")
    assert table_para.from_table is False
    assert table_para.table_position is None


def test_extract_docx_separator_footnotes_are_never_extracted(tmp_path):
    # A real separator/continuationSeparator footnote's body has no actual text (just
    # a <w:separator/> marker element), and the body never actually references its id
    # either - so excluding it by w:type wouldn't visibly change round-trip output on
    # its own (nothing looks it up, and even if something did, it has no text to show).
    # To genuinely exercise the w:type gate end-to-end, this constructs a deliberately
    # unrealistic separator footnote that DOES carry real paragraph text, AND adds a
    # body reference to its id - proving it's excluded even when referenced, not just
    # coincidentally unreachable.
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    p = doc.add_paragraph("Claim.")
    _add_footnote_reference(p, "-1")
    _add_footnote_reference(p, "1")
    doc.save(str(file_path))
    footnotes_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:footnotes xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:footnote w:type="separator" w:id="-1">'
        + _paragraph_xml("This text should never be extracted.") + '</w:footnote>'
        '<w:footnote w:id="1">' + _paragraph_xml("Real citation.") + '</w:footnote>'
        '</w:footnotes>'
    )
    with zipfile.ZipFile(str(file_path), "r") as zin:
        names = zin.namelist()
        content_types_xml = zin.read("[Content_Types].xml").decode("utf-8")
        rels_xml = zin.read("word/_rels/document.xml.rels").decode("utf-8")
        other = {n: zin.read(n) for n in names if n not in ("[Content_Types].xml", "word/_rels/document.xml.rels")}
    content_types_xml = content_types_xml.replace(
        "</Types>",
        '<Override PartName="/word/footnotes.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml"/></Types>',
    )
    rels_xml = rels_xml.replace(
        "</Relationships>",
        '<Relationship Id="rIdFootnotes" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footnotes" '
        'Target="footnotes.xml"/></Relationships>',
    )
    with zipfile.ZipFile(str(file_path), "w", zipfile.ZIP_DEFLATED) as zout:
        zout.writestr("[Content_Types].xml", content_types_xml)
        zout.writestr("word/_rels/document.xml.rels", rels_xml)
        zout.writestr("word/footnotes.xml", footnotes_xml)
        for name, data in other.items():
            zout.writestr(name, data)

    paragraphs = extract_text(str(file_path), "docx")

    texts = [par.text for par in paragraphs]
    assert "Real citation." in texts
    assert "This text should never be extracted." not in texts


def test_extract_docx_without_footnotes_is_unchanged(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    doc.add_paragraph("Plain paragraph, no footnotes at all.")
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")

    assert [par.text for par in paragraphs] == ["Plain paragraph, no footnotes at all."]


def test_extract_docx_reference_to_missing_footnote_id_is_skipped(tmp_path):
    # Defensive case: a <w:footnoteReference> whose w:id has no matching <w:footnote>
    # in footnotes.xml (a malformed document) is skipped silently, and extraction of
    # everything else proceeds normally.
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    p = doc.add_paragraph("Claim with a dangling footnote reference.")
    _add_footnote_reference(p, "99")
    _save_docx_with_footnotes(doc, str(file_path), [("1", ["Unrelated real footnote, different id."])])

    paragraphs = extract_text(str(file_path), "docx")

    texts = [par.text for par in paragraphs]
    assert texts == ["Claim with a dangling footnote reference."]
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_extraction.py -k footnote -v`
Expected: 5 of the 7 new tests FAIL (assertion failures — `"Footnote 1"` missing from output, since wiring doesn't exist yet): `test_extract_docx_single_footnote_is_extracted`, `test_extract_docx_multiple_footnotes_get_sequential_numbers_in_reference_order`, `test_extract_docx_footnote_content_has_correct_default_fields`, `test_extract_docx_footnote_with_nested_table_is_extracted`, `test_extract_docx_separator_footnotes_are_never_extracted`. The other 2 (`test_extract_docx_without_footnotes_is_unchanged`, `test_extract_docx_reference_to_missing_footnote_id_is_skipped`) already pass even without the wiring — there's nothing for either scenario to break yet, since no footnote content is emitted at all pre-wiring. Both are still worth keeping as explicit regression tests once the wiring lands in Step 4. The 5 tests from Task 1 continue to pass throughout.

- [ ] **Step 4: Wire footnote extraction into `_extract_docx`**

In `backend/app/extraction.py`, find the first loop inside `_extract_docx`:

```python
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
```

Replace with (adds footnote-reference collection to the existing loop, so no second body walk is needed):

```python
    paragraphs: list[Paragraph] = []
    index = 0
    footnote_refs_in_order: list[str] = []
    for para, allow_text_pattern_heading, from_table, table_position in _iter_docx_paragraphs(
        doc.iter_inner_content(), table_id_counter=table_id_counter
    ):
        # Collecting footnote reference ids here, in the same walk that already visits
        # every body paragraph, avoids a second full-body traversal just to find them.
        for ref in para._p.findall(".//" + qn("w:footnoteReference")):
            footnote_refs_in_order.append(ref.get(qn("w:id")))
        model = _docx_paragraph_to_model(
            para, index, baseline_pt, allow_text_pattern_heading, from_table, table_position
        )
        if model is not None:
            paragraphs.append(model)
            index += 1
```

Then find the end of the text-box block and the function's `return`:

```python
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

Replace with (adds the footnote emission block between the text-box block and the return):

```python
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

    footnotes_root = _footnotes_root(doc)
    if footnotes_root is not None and footnote_refs_in_order:
        footnote_content_by_id = _footnote_content_by_id(footnotes_root, doc)
        footnote_number = 0
        for footnote_id in footnote_refs_in_order:
            group = footnote_content_by_id.get(footnote_id)
            if not group:
                continue
            group = [p for p in group if p.text.strip()]
            if not group:
                continue
            footnote_number += 1
            paragraphs.append(Paragraph(text=f"Footnote {footnote_number}", paragraph_index=index, is_heading=True))
            index += 1
            for footnote_para in group:
                model = _docx_paragraph_to_model(footnote_para, index, baseline_pt, allow_text_pattern_heading=False)
                if model is not None:
                    paragraphs.append(model)
                    index += 1

    return paragraphs
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_extraction.py -k footnote -v`
Expected: 12 passed (5 from Task 1, 7 new from this task).

- [ ] **Step 6: Add the renumbering-safety guard to `section_structure.py`**

In `backend/app/section_structure.py`, find:

```python
_TEXT_BOX_PATTERN = re.compile(r"^Text Box \d+$")


def _is_text_box_heading(heading: str) -> bool:
    return bool(_TEXT_BOX_PATTERN.match(heading))


def detect_section_reordering(
```

Replace with:

```python
_TEXT_BOX_PATTERN = re.compile(r"^Text Box \d+$")


def _is_text_box_heading(heading: str) -> bool:
    return bool(_TEXT_BOX_PATTERN.match(heading))


_FOOTNOTE_PATTERN = re.compile(r"^Footnote \d+$")


def _is_footnote_heading(heading: str) -> bool:
    return bool(_FOOTNOTE_PATTERN.match(heading))


def detect_section_reordering(
```

Then find, inside `detect_section_heading_changed`:

```python
        if _is_text_box_heading(old_heading) or _is_text_box_heading(new_heading):
            continue
        old_split = _split_heading_number(old_heading)
```

Replace with:

```python
        if _is_text_box_heading(old_heading) or _is_text_box_heading(new_heading):
            continue
        if _is_footnote_heading(old_heading) or _is_footnote_heading(new_heading):
            continue
        old_split = _split_heading_number(old_heading)
```

- [ ] **Step 7: Write the failing unit tests for the guard**

In `backend/tests/test_section_structure.py`, find `test_text_box_added_is_still_flagged_as_section_added` (added by the text-box plan's final-review fix) and add these two tests immediately after it:

```python
def test_footnote_renumbering_is_not_flagged_as_heading_changed():
    old_sections = [Section(heading="Footnote 1", paragraphs=[Paragraph(text="See ICH Q1A(R2).")])]
    new_sections = [Section(heading="Footnote 2", paragraphs=[Paragraph(text="See ICH Q1A(R2).")])]
    matches = [SectionMatch(old_index=0, new_index=0, score=1.0)]

    assert detect_section_heading_changed(matches, old_sections, new_sections) == []


def test_footnote_added_is_still_flagged_as_section_added():
    # Regression guard proving the narrower fix does NOT suppress section_added
    # for a genuinely new footnote (mirrors test_text_box_added_is_still_flagged_as_section_added).
    new_sections = [Section(heading="Footnote 1", paragraphs=[Paragraph(text="New citation.")])]

    changes = detect_section_added([0], new_sections)

    assert len(changes) == 1
    assert changes[0].change_type == "section_added"
```

- [ ] **Step 8: Run the tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_section_structure.py -k footnote -v`
Expected: `test_footnote_renumbering_is_not_flagged_as_heading_changed` FAILS (the guard doesn't exist yet, so this currently produces a `section_heading_changed`). `test_footnote_added_is_still_flagged_as_section_added` PASSES already (nothing about `detect_section_added` needs to change — this test exists to prove that stays true).

- [ ] **Step 9: Run the tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_section_structure.py -k footnote -v`
Expected: 2 passed.

- [ ] **Step 10: Write the failing pipeline regression test**

In `backend/tests/test_pipeline.py`, find `_add_text_box_paragraph` (added by the text-box plan's final-review fix) and add the footnote fixture helpers immediately after it, followed by the regression test:

```python
def _add_footnote_reference(paragraph, footnote_id):
    p = paragraph._p
    r = p.makeelement(qn("w:r"), {})
    ref = r.makeelement(qn("w:footnoteReference"), {qn("w:id"): str(footnote_id)})
    r.append(ref)
    p.append(r)


def _save_docx_with_footnotes(doc, path, footnotes):
    doc.save(path)
    footnote_blocks = "".join(
        f'<w:footnote w:id="{fid}">'
        + "".join(f'<w:p><w:r><w:t xml:space="preserve">{t}</w:t></w:r></w:p>' for t in texts)
        + "</w:footnote>"
        for fid, texts in footnotes
    )
    footnotes_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:footnotes xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:footnote w:type="separator" w:id="-1"><w:p><w:r><w:separator/></w:r></w:p></w:footnote>'
        '<w:footnote w:type="continuationSeparator" w:id="0">'
        '<w:p><w:r><w:continuationSeparator/></w:r></w:p></w:footnote>'
        f'{footnote_blocks}'
        '</w:footnotes>'
    )
    with zipfile.ZipFile(path, "r") as zin:
        names = zin.namelist()
        content_types_xml = zin.read("[Content_Types].xml").decode("utf-8")
        rels_xml = zin.read("word/_rels/document.xml.rels").decode("utf-8")
        other = {n: zin.read(n) for n in names if n not in ("[Content_Types].xml", "word/_rels/document.xml.rels")}
    content_types_xml = content_types_xml.replace(
        "</Types>",
        '<Override PartName="/word/footnotes.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml"/></Types>',
    )
    rels_xml = rels_xml.replace(
        "</Relationships>",
        '<Relationship Id="rIdFootnotes" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footnotes" '
        'Target="footnotes.xml"/></Relationships>',
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zout:
        zout.writestr("[Content_Types].xml", content_types_xml)
        zout.writestr("word/_rels/document.xml.rels", rels_xml)
        zout.writestr("word/footnotes.xml", footnotes_xml)
        for name, data in other.items():
            zout.writestr(name, data)


def test_pipeline_adding_an_earlier_footnote_does_not_falsely_flag_later_one_as_changed():
    # Regression test mirroring test_pipeline_adding_an_earlier_text_box_does_not_falsely_flag_later_one_as_changed:
    # adding an earlier footnote reference shifts every later footnote's "Footnote N"
    # number, even though its own content never changed. Without the guard added in
    # this plan, this would spuriously produce section_heading_changed findings like
    # "Footnote 1" -> "Footnote 2".
    with tempfile.TemporaryDirectory() as tmp_dir:
        old_path = os.path.join(tmp_dir, "old.docx")
        new_path = os.path.join(tmp_dir, "new.docx")

        old_doc = DocxDocument()
        old_p = old_doc.add_paragraph("Store samples per the stability protocol.")
        _add_footnote_reference(old_p, "1")
        _save_docx_with_footnotes(old_doc, old_path, [("1", ["Store samples at 25 C."])])

        new_doc = DocxDocument()
        new_p1 = new_doc.add_paragraph("Revision history updated for this release.")
        _add_footnote_reference(new_p1, "1")
        new_p2 = new_doc.add_paragraph("Store samples per the stability protocol.")
        _add_footnote_reference(new_p2, "2")
        _save_docx_with_footnotes(new_doc, new_path, [
            ("1", ["NOTE: revision history updated."]),
            ("2", ["Store samples at 25 C."]),
        ])

        old_paragraphs = extract_text(old_path, "docx")
        new_paragraphs = extract_text(new_path, "docx")

    result = pipeline.compare_documents(old_paragraphs, new_paragraphs, "old.docx", "new.docx")

    heading_changed = [c for c in result.changes if c.change_type == "section_heading_changed"]
    assert heading_changed == []
```

Add `import zipfile` to the top of `test_pipeline.py` (alongside the existing `import os` / `import tempfile`).

- [ ] **Step 11: Confirm the test actually exercises the bug**

By this point in the task, Step 6's guard is already in place (uncommitted), so this test will currently PASS — which on its own doesn't prove it's testing anything real. Prove it by temporarily removing the guard and confirming the test fails without it:

```bash
cd backend
git stash push -- app/section_structure.py
python -m pytest tests/test_pipeline.py -k footnote -v
git stash pop
```

Expected: with the guard stashed away, the test FAILS (`heading_changed` is non-empty — the exact spurious `"Footnote 1" -> "Footnote 2"` finding the guard prevents). `git stash pop` restores the guard afterward.

- [ ] **Step 12: Run the test to verify it passes with the guard restored**

Run: `cd backend && python -m pytest tests/test_pipeline.py -k footnote -v`
Expected: PASS.

- [ ] **Step 13: Run the full backend suite**

Run: `cd backend && python -m pytest -q`
Expected: all tests pass (243 from Task 1 + 7 extraction round-trip + 2 section_structure + 1 pipeline = 253 passed).

- [ ] **Step 14: Commit**

```bash
git add backend/app/extraction.py backend/app/section_structure.py backend/tests/test_extraction.py backend/tests/test_section_structure.py backend/tests/test_pipeline.py
git commit -m "feat: extract footnote content as Footnote N pseudo-sections"
```
