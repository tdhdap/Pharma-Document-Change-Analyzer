# Text Box and Footnote Anchoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make text box and footnote pseudo-section labels carry the item's location in the document, so a reviewer can trace a change back to where it lives.

**Architecture:** `_extract_docx` already walks every body paragraph and already harvests footnote reference ids during that walk. It gains a running "current section heading + paragraphs seen since it" state, and records an anchor label for each footnote reference and each `w:txbxContent` element it passes. The existing text-box and footnote emission passes are unchanged except for looking that anchor up. Two suppression regexes widen so anchored labels keep behaving like the un-anchored ones did.

**Tech Stack:** Python 3.14, python-docx, lxml, pytest.

## Global Constraints

- **`backend/app/section_structure.py` has unrelated uncommitted work in the working tree** that the user intends to commit separately. Stage only the specific files you changed, by name. **Never `git add -A`, never `git commit -a`.**
- Never read or write `backend/app.db` — it is the user's real database.
- **Display only.** No new change type, no new risk-table entry, no detection of relocation. A changed anchor must report nothing.
- No schema change and no migration: nothing new is persisted.
- The full backend suite is green at 326 tests before this work starts and must be green after every task.
- PDF and TXT extraction must not change.

## Prior verification

The whole design was prototyped against the live code and reverted before this plan was written. The exact code below is the code that ran. Findings that shaped it:

- Anchor discovery per body paragraph found **exactly** the same `w:txbxContent` elements as the current body-root search, on all four corpus documents that contain text boxes.
- `model.is_heading` is **not** the right heading test. It reflects only Word style and font size, while `split_into_sections` also treats numbered and ALL-CAPS text as headings. They disagree on **10 corpus documents** (`RECORD RETENTION`, `1.0 Scope`, `2.0 Sample Preparation`, …). Using `model.is_heading` anchors items in those documents to the wrong section. Use `sectioning._is_heading_paragraph`.
- Without the Task 1 pattern widening, two existing pipeline tests fail with spurious `section_heading_changed` rows. With it, they pass.
- On the real corpus the text box's anchor genuinely differs between versions (`7.0 References` → `8.0 Training Requirements`, because a section was added above it) and correctly produces **no** change row.

## File Structure

- `backend/app/section_structure.py` — two regex constants widen. Nothing else.
- `backend/app/extraction.py` — one new module-level helper (`_anchor_label`), one changed generator signature (`_iter_text_box_paragraphs`), and anchor tracking inside `_extract_docx`.
- `backend/tests/test_section_structure.py` — new tests for the widened patterns.
- `backend/tests/test_extraction.py` — updates to 16 existing tests, plus new anchor tests.

---

### Task 1: Widen the pseudo-heading suppression patterns

Do this first. It is safe on today's labels — the new group is optional, so `Text Box 1` still matches — and it means the suite never goes red when Task 2 changes the labels.

**Files:**
- Modify: `backend/app/section_structure.py:131`, `backend/app/section_structure.py:138`
- Test: `backend/tests/test_section_structure.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `_is_text_box_heading(heading)` and `_is_footnote_heading(heading)` now return `True` for labels carrying a parenthetical anchor suffix.

- [ ] **Step 1: Write the failing tests**

This file imports names directly and does **not** bind the module name, so
first extend its existing import — add the two predicates to the
`from app.section_structure import (...)` block already at the top:

```python
from app.section_structure import (
    detect_section_renumbering, detect_section_reordering,
    detect_section_added, detect_section_deleted, detect_section_heading_changed,
    _summarize_section_content, _is_text_box_heading, _is_footnote_heading,
)
```

Then append to `backend/tests/test_section_structure.py`:

```python
def test_is_text_box_heading_accepts_an_anchored_label():
    assert _is_text_box_heading("Text Box 1")
    assert _is_text_box_heading("Text Box 1 (8.0 Training Requirements, after paragraph 1)")
    assert _is_text_box_heading("Text Box 1 (9.0 Training Log, at start)")


def test_is_text_box_heading_accepts_the_nested_parentheses_a_header_anchor_produces():
    # A header/footer label is itself parenthesised, so a text box anchored to one
    # yields nested parentheses. The greedy .+ must consume the inner pair.
    assert _is_text_box_heading("Text Box 3 (Page Footer (First Page))")


def test_is_text_box_heading_still_rejects_non_labels():
    assert not _is_text_box_heading("Text Box")
    assert not _is_text_box_heading("My Text Box 1")


def test_is_footnote_heading_accepts_an_anchored_label():
    assert _is_footnote_heading("Footnote 1")
    assert _is_footnote_heading("Footnote 12 (4.0 Procedure, paragraph 1)")


def test_is_footnote_heading_still_rejects_non_labels():
    assert not _is_footnote_heading("Footnote")
    assert not _is_footnote_heading("See Footnote 1")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_section_structure.py -k "anchored_label or nested_parentheses" -v`
Expected: FAIL — the anchored labels do not match `^Text Box \d+$`.

- [ ] **Step 3: Widen the two patterns**

In `backend/app/section_structure.py`, replace exactly these two lines:

```python
_TEXT_BOX_PATTERN = re.compile(r"^Text Box \d+(\s\(.+\))?$")
```

```python
_FOOTNOTE_PATTERN = re.compile(r"^Footnote \d+(\s\(.+\))?$")
```

This mirrors `_PAGE_HEADER_FOOTER_PATTERN` (`^Page (Header|Footer)(\s\(.+\))?$`), which already tolerates a parenthetical for the same reason.

Add above `_TEXT_BOX_PATTERN`:

```python
# The optional group tolerates the location anchor the label carries (e.g.
# "Text Box 1 (4.0 Procedure, paragraph 2)"). Without it, every anchored label
# whose section or position differed between versions would emit a spurious
# section_heading_changed row - verified: two pipeline tests fail without this.
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_section_structure.py -q`
Expected: PASS.

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && python -m pytest -q`
Expected: all pass (326 + the 5 new tests). The optional group leaves today's un-anchored labels matching exactly as before.

- [ ] **Step 6: Commit**

```bash
git add backend/app/section_structure.py backend/tests/test_section_structure.py
git commit -m "feat: tolerate a location anchor in text box and footnote labels"
```

**Do not use `git add -A`.** `backend/app/section_structure.py` also contains the user's unrelated uncommitted work — verify with `git diff --cached backend/app/section_structure.py` that your commit contains only the two pattern lines and the comment, and nothing else.

---

### Task 2: Anchor text boxes to their location

**Files:**
- Modify: `backend/app/extraction.py` (import line 12, `_iter_text_box_paragraphs`, new `_anchor_label`, `_extract_docx`)
- Test: `backend/tests/test_extraction.py`

**Interfaces:**
- Consumes: `sectioning._is_heading_paragraph(paragraph) -> bool`.
- Produces: `_anchor_label(heading: str, paragraphs_before: int, inside_paragraph: bool) -> str`; `_iter_text_box_paragraphs` now yields `(txbx_element, [DocxParagraph, ...])` instead of just the list; `_extract_docx` builds a local `text_box_anchors: dict[element, str]` that Task 3 also reads.

- [ ] **Step 1: Write the failing tests**

This file also imports names directly and does **not** bind the module
name, so first add a new import line beside the existing
`from app.extraction import ...` lines:

```python
from app.extraction import _anchor_label
```

Then append to `backend/tests/test_extraction.py`:

```python
def test_anchor_label_inside_an_emitted_paragraph():
    assert _anchor_label("4.0 Procedure", 0, True) == "4.0 Procedure, paragraph 1"
    assert _anchor_label("4.0 Procedure", 2, True) == "4.0 Procedure, paragraph 3"


def test_anchor_label_between_paragraphs_when_the_anchor_was_dropped():
    assert _anchor_label("8.0 Training", 1, False) == "8.0 Training, after paragraph 1"


def test_anchor_label_at_start_when_nothing_precedes_it():
    # "after paragraph 0" would be nonsense; a real corpus text box hits this.
    assert _anchor_label("9.0 Training Log", 0, False) == "9.0 Training Log, at start"


def test_extract_docx_text_box_anchor_names_the_enclosing_heading(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    doc.add_heading("4.0 Procedure", level=1)
    doc.add_paragraph("Body paragraph under the heading.")
    _add_text_box(doc.element.body, ["Callout content."])
    doc.save(str(file_path))

    texts = [p.text for p in extract_text(str(file_path), "docx")]

    assert "Text Box 1 (4.0 Procedure, after paragraph 1)" in texts


def test_extract_docx_text_box_anchor_uses_a_text_pattern_heading(tmp_path):
    # The heading test must be sectioning._is_heading_paragraph, not model.is_heading.
    # An ALL-CAPS heading has no Heading style, so model.is_heading is False for it,
    # but split_into_sections treats it as a heading - 10 corpus documents rely on this.
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    doc.add_paragraph("Opening body text.")
    doc.add_paragraph("RECORD RETENTION")
    doc.add_paragraph("Records are retained for five years.")
    _add_text_box(doc.element.body, ["Callout content."])
    doc.save(str(file_path))

    texts = [p.text for p in extract_text(str(file_path), "docx")]

    assert "Text Box 1 (RECORD RETENTION, after paragraph 1)" in texts


def test_extract_docx_two_text_boxes_at_one_position_stay_distinguishable(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    _add_text_box(doc.element.body, ["First box."])
    _add_text_box(doc.element.body, ["Second box."])
    doc.save(str(file_path))

    texts = [p.text for p in extract_text(str(file_path), "docx")]

    assert "Text Box 1 (Preamble, at start)" in texts
    assert "Text Box 2 (Preamble, at start)" in texts
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_extraction.py -k "anchor" -v`
Expected: FAIL — `_anchor_label` does not exist, and the labels are bare ordinals.

- [ ] **Step 3: Add the import**

In `backend/app/extraction.py`, change line 12 to:

```python
from app.sectioning import _is_heading_paragraph, _looks_like_heading_shape
```

- [ ] **Step 4: Add the `_anchor_label` helper**

Add immediately after `_iter_text_box_paragraphs`:

```python
def _anchor_label(heading: str, paragraphs_before: int, inside_paragraph: bool) -> str:
    # One rule, keyed on whether the anchoring paragraph survived extraction. A
    # footnote normally lives inside a real paragraph, while Word parks a floating
    # text box in a paragraph of its own with no text - which _docx_paragraph_to_model
    # drops - so the box sits between paragraphs rather than in one. Verified on the
    # real corpus: every text box anchor paragraph was empty, every footnote's was not.
    if inside_paragraph:
        return f"{heading}, paragraph {paragraphs_before + 1}"
    if paragraphs_before == 0:
        return f"{heading}, at start"
    return f"{heading}, after paragraph {paragraphs_before}"
```

- [ ] **Step 5: Yield the element from `_iter_text_box_paragraphs`**

Replace the final line of `_iter_text_box_paragraphs`:

```python
        yield txbx, [para for para, _, _, _ in _iter_docx_paragraphs(_content_iter(txbx, doc))]
```

The element is yielded so the caller can look the box's anchor up. Callers key on the **element object**, never `id()` — lxml only guarantees a stable `id()` while a reference to the proxy is alive, the same trap documented in the table merge-span pre-pass above.

- [ ] **Step 6: Track section state and text box anchors in `_extract_docx`**

Replace the loop header and body. Before:

```python
    footnote_refs_in_order: list[str] = []
    seen_footnote_ids: set[str] = set()
    for para, allow_text_pattern_heading, from_table, table_position in _iter_docx_paragraphs(
        doc.iter_inner_content(), table_id_counter=table_id_counter
    ):
```

After:

```python
    footnote_refs_in_order: list[tuple[str, str]] = []
    seen_footnote_ids: set[str] = set()
    text_box_anchors: dict = {}
    anchor_heading = "Preamble"
    anchor_paragraph_count = 0
    for para, allow_text_pattern_heading, from_table, table_position in _iter_docx_paragraphs(
        doc.iter_inner_content(), table_id_counter=table_id_counter
    ):
        # The model is built first so the anchor can tell whether this paragraph will
        # actually be emitted. _is_heading_paragraph - not model.is_heading - is the
        # boundary test, because it is the same predicate split_into_sections uses;
        # model.is_heading misses numbered and ALL-CAPS headings, which 10 corpus
        # documents contain.
        model = _docx_paragraph_to_model(
            para, index, baseline_pt, allow_text_pattern_heading, from_table, table_position
        )
        in_heading = model is not None and _is_heading_paragraph(model)
        if in_heading:
            anchor_heading = model.text
            anchor_paragraph_count = 0
        anchor = _anchor_label(
            anchor_heading, anchor_paragraph_count, model is not None and not in_heading
        )
        for txbx in para._p.findall(".//" + qn("w:txbxContent")):
            if _has_mc_fallback_ancestor(txbx):
                continue
            text_box_anchors[txbx] = anchor
```

Then delete the now-duplicated `model = _docx_paragraph_to_model(...)` call that sits after the footnote-reference loop, and replace the emission block. Before:

```python
        if model is not None:
            paragraphs.append(model)
            index += 1
```

After:

```python
        if model is not None:
            paragraphs.append(model)
            index += 1
            if not in_heading:
                anchor_paragraph_count += 1
```

- [ ] **Step 7: Use the anchor when emitting text boxes**

Replace the text box pass. Before:

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
```

After:

```python
    # A header/footer box has no body paragraph to anchor to, so it falls back to that
    # header/footer's own label and carries no ordinal - "paragraph 3 of the footer" is
    # not a location anyone navigates to.
    text_box_roots = [(doc.element.body, None)] + [
        (source._element, _header_footer_heading_text(kind, section_index, variant_label, multi_section))
        for kind, section_index, variant_label, source in header_footer_specs
    ]
    text_box_number = 0
    for root_element, fallback_anchor in text_box_roots:
        for txbx, group in _iter_text_box_paragraphs(root_element, doc):
            group = [p for p in group if p.text.strip()]
            if not group:
                continue
            text_box_number += 1
            anchor = text_box_anchors.get(txbx, fallback_anchor)
            label = f"Text Box {text_box_number}" + (f" ({anchor})" if anchor else "")
            paragraphs.append(Paragraph(text=label, paragraph_index=index, is_heading=True))
```

Emission order and numbering are deliberately unchanged: the boxes are still discovered by the same body-root search in the same order, so paragraph ordering and every downstream section boundary are untouched. A box the walk somehow missed still emits — it just carries no anchor.

- [ ] **Step 8: Update the 8 `_iter_text_box_paragraphs` tests for the 2-tuple yield**

These tests fail with `AttributeError: 'list' object has no attribute 'text'` because they unpack the old single value. In each of:

`test_iter_text_box_paragraphs_finds_drawingml_text_box`,
`test_iter_text_box_paragraphs_finds_vml_text_box`,
`test_iter_text_box_paragraphs_joins_multiple_runs`,
`test_iter_text_box_paragraphs_finds_multiple_text_boxes_as_separate_groups`,
`test_iter_text_box_paragraphs_finds_text_box_inside_table_cell`,
`test_iter_text_box_paragraphs_handles_nested_text_box_as_separate_group`,
`test_iter_text_box_paragraphs_deduplicates_word_mc_alternate_content`,
`test_iter_text_box_paragraphs_extracts_nested_table_content`

change the collection line from the form `groups = list(_iter_text_box_paragraphs(...))` to discard the element:

```python
    groups = [group for _txbx, group in _iter_text_box_paragraphs(root, doc)]
```

Keep every existing assertion exactly as it is. These tests are about content, not anchoring.

- [ ] **Step 9: Update the 3 text box label assertions**

- `test_extract_docx_text_box_in_body_is_extracted`: expect `"Text Box 1 (Preamble, after paragraph 1)"`.
- `test_extract_docx_multiple_text_boxes_get_sequential_numbers`: expect `"Text Box 1 (Preamble, at start)"` and `"Text Box 2 (Preamble, at start)"`.
- `test_extract_docx_text_box_inside_active_first_page_header_is_extracted`: expect `"Text Box 1 (Page Header (First Page))"`. The nested parentheses are correct and Task 1's pattern accepts them.

- [ ] **Step 10: Run the tests**

Run: `cd backend && python -m pytest tests/test_extraction.py -q`
Expected: all pass except the 5 footnote label tests, which Task 3 owns.

- [ ] **Step 11: Commit**

```bash
git add backend/app/extraction.py backend/tests/test_extraction.py
git commit -m "feat: anchor text box labels to their location in the document"
```

Stage only these two files.

---

### Task 3: Anchor footnotes to their location

**Files:**
- Modify: `backend/app/extraction.py` (`_extract_docx` footnote-reference collection and footnote emission)
- Test: `backend/tests/test_extraction.py`

**Interfaces:**
- Consumes: `_anchor_label` and the `anchor` local from Task 2.
- Produces: `footnote_refs_in_order` becomes `list[tuple[str, str]]` of `(footnote_id, anchor_label)`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_extraction.py`:

```python
def test_extract_docx_footnote_anchor_names_the_paragraph_it_sits_in(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    doc.add_heading("4.0 Procedure", level=1)
    doc.add_paragraph("First body paragraph.")
    p = doc.add_paragraph("Second body paragraph.")
    _add_footnote_reference(p, "1")
    _save_docx_with_footnotes(doc, str(file_path), [("1", ["Citation text."])])

    texts = [par.text for par in extract_text(str(file_path), "docx")]

    assert "Footnote 1 (4.0 Procedure, paragraph 2)" in texts


def test_extract_docx_footnote_in_a_paragraph_with_no_text_anchors_between(tmp_path):
    # A paragraph holding only the reference marker is dropped by
    # _docx_paragraph_to_model, so the shared rule reports it as between paragraphs.
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    doc.add_paragraph("Body paragraph.")
    p = doc.add_paragraph("")
    _add_footnote_reference(p, "1")
    _save_docx_with_footnotes(doc, str(file_path), [("1", ["Citation text."])])

    texts = [par.text for par in extract_text(str(file_path), "docx")]

    assert "Footnote 1 (Preamble, after paragraph 1)" in texts
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_extraction.py -k "footnote_anchor or footnote_in_a_paragraph_with_no_text" -v`
Expected: FAIL — labels are bare ordinals.

- [ ] **Step 3: Record the anchor with each reference**

In `_extract_docx`, the footnote-reference loop now runs after the model is built (Task 2 moved it there). Change its final line:

```python
            footnote_refs_in_order.append((ref_id, anchor))
```

Leave the `_has_mc_fallback_ancestor` guard and the `seen_footnote_ids` dedupe exactly as they are — they still guard Word's duplicated DrawingML/VML copies and a footnote genuinely referenced twice.

- [ ] **Step 4: Use the anchor when emitting footnotes**

Replace the emission block. Before:

```python
        for footnote_id in footnote_refs_in_order:
```

After:

```python
        for footnote_id, anchor in footnote_refs_in_order:
```

and replace the label line:

```python
            label = f"Footnote {footnote_number}" + (f" ({anchor})" if anchor else "")
            paragraphs.append(Paragraph(text=label, paragraph_index=index, is_heading=True))
```

- [ ] **Step 5: Update the 5 footnote label assertions**

- `test_extract_docx_single_footnote_is_extracted`: `"Footnote 1 (Preamble, paragraph 1)"`.
- `test_extract_docx_multiple_footnotes_get_sequential_numbers_in_reference_order`: `"Footnote 1 (Preamble, paragraph 1)"` and `"Footnote 2 (Preamble, paragraph 2)"`.
- `test_extract_docx_footnote_with_nested_table_is_extracted`: `"Footnote 1 (Preamble, paragraph 1)"`.
- `test_extract_docx_footnote_referenced_from_inside_text_box_is_extracted`: `"Footnote 1 (Preamble, after paragraph 1)"`, and its text box becomes `"Text Box 1 (Preamble, after paragraph 1)"`. The hosting body paragraph contains only the drawing, so it is dropped.
- `test_extract_docx_footnote_in_mc_alternate_content_text_box_is_extracted_once`: `"Footnote 1 (Preamble, at start)"`, and its text box becomes `"Text Box 1 (Preamble, at start)"`. That document begins with the drawing paragraph, so nothing precedes it.

- [ ] **Step 6: Add the end-to-end suppression regression**

Append to `backend/tests/test_pipeline.py`. This is the assertion that enforces the display-only decision:

```python
def test_pipeline_a_text_box_whose_anchor_changed_reports_no_heading_change(monkeypatch):
    # Adding a section above a text box shifts its anchor without the box moving.
    # This happens for real in the corpus (7.0 References -> 8.0 Training Requirements)
    # and must stay silent: anchoring is traceability, not a finding.
    monkeypatch.setattr(llm_classifier, "classify_changes_batch", lambda items, *a, **k: [])

    old_paragraphs = [
        Paragraph(text="1.0 Scope", paragraph_index=0, is_heading=True),
        Paragraph(text="Applies to all batches.", paragraph_index=1),
        Paragraph(text="Text Box 1 (1.0 Scope, after paragraph 1)", paragraph_index=2, is_heading=True),
        Paragraph(text="CAUTION: verify calibration.", paragraph_index=3),
    ]
    new_paragraphs = [
        Paragraph(text="1.0 Scope", paragraph_index=0, is_heading=True),
        Paragraph(text="Applies to all batches.", paragraph_index=1),
        Paragraph(text="Text Box 1 (2.0 Responsibilities, after paragraph 1)", paragraph_index=2, is_heading=True),
        Paragraph(text="CAUTION: verify calibration.", paragraph_index=3),
    ]

    result = pipeline.compare_documents(old_paragraphs, new_paragraphs, "v1.docx", "v2.docx")

    assert [c for c in result.changes if c.change_type == "section_heading_changed"] == []
```

Follow the file's existing import and monkeypatch conventions if they differ from the above.

- [ ] **Step 7: Run the full backend suite**

Run: `cd backend && python -m pytest -q`
Expected: all pass.

- [ ] **Step 8: Corpus sweep**

Extract every DOCX in `test-documents/docx/` before and after this branch and diff the paragraph text lists. Expected: the **only** differences anywhere are `Text Box N` and `Footnote N` labels gaining their suffix. Any other difference is a regression — in particular, no paragraph may change position, since section boundaries depend on ordering.

- [ ] **Step 9: Commit**

```bash
git add backend/app/extraction.py backend/tests/test_extraction.py backend/tests/test_pipeline.py
git commit -m "feat: anchor footnote labels to the paragraph they belong to"
```

Stage only these three files.
