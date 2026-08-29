# Full-Coverage Test Documents Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One DOCX pair that provably produces all 22 deterministic change types, built by a committed, reviewable generator script and guarded by an automated test.

**Architecture:** A data-driven generator in `scripts/generate_full_coverage_docs.py` builds both documents from declarative section and table specs. Body content, tables, text boxes and footnotes are added by four small builder helpers, three of which mirror techniques already proven in `backend/tests/test_extraction.py`. A regression test asserts the full type set with the LLM stubbed.

**Tech Stack:** Python 3.14, python-docx, lxml, raw OOXML/OPC manipulation, pytest.

## Global Constraints

- **The generated documents must open in Microsoft Word.** Two known causes of rejection, both designed around below. pytest cannot detect this — opening both files is a manual acceptance step.
- The pair guarantees the **22 deterministic** types only. The 6 LLM types are written for but never asserted.
- Never read or write `backend/app.db` — the user's real database.
- **The working tree holds the user's uncommitted work in several unrelated files.** Stage by name. **Never `git add -A`, never `git commit -a`.** If you cannot stage a file, **STOP and report** — never reconstruct a file from HEAD.
- Do not modify any existing document in `test-documents/docx/`, and do not modify `backend/tests/test_extraction.py`.
- Backend is green at 353 tests, frontend at 85, before this work starts.

## Prior verification

Two load-bearing facts were confirmed against the live detectors before this plan was written.

**The cascade arithmetic.** `section_renumbered_cascade` fires only when the number shift equals (numbered sections inserted above) minus (numbered sections deleted above). Insertion and deletion both above the same section cancel to zero and produce **no row at all**. Verified:

```
v1: 1.0 Purpose  2.0 Scope  3.0 Equipment  4.0 Records  5.0 Legacy Annex
v2: 1.0 Purpose  2.0 Scope  3.0 Responsibilities  4.0 Equipment  6.0 Records

section_renumbered_cascade  '3.0 Equipment' -> '4.0 Equipment'
section_renumbered          '4.0 Records'   -> '6.0 Records'
```

The insertion must sit **above** the cascade sections and the deletion **below** them.

**The summary string.** `_summarize_section_content` returns exactly `"3 paragraphs, 1 table."` for 3 body paragraphs plus one table. The deleted section is built to match.

## File Structure

- `scripts/generate_full_coverage_docs.py` — new, self-contained generator.
- `test-documents/docx/FullCoverageDemo_v1.docx`, `_v2.docx` — generated output, committed.
- `backend/tests/test_full_coverage_corpus.py` — new regression test.
- `docs/full-coverage-demo-expected-results.md` — the expected-results table.

`scripts/generate_test_documents.py` already exists and builds the A/B/C1/C2/SOP
pairs. Read it first: its `generate_and_validate` pattern — write the file, then
re-extract it and assert the heading sequence — is the convention this generator
follows. It is section-only (no tables, text boxes or footnotes), which is why
this is a new module rather than more scenario constants in that file. Do not
modify it.

**The generator carries its own copies of the OOXML helpers.** `_add_text_box`, `_add_footnote_reference` and `_save_docx_with_footnotes` currently live as private names inside `backend/tests/test_extraction.py`. Importing private names from a test module into a script is fragile, and lifting them into a shared module would touch a large, currently-green test file for no behavioural gain. The duplication is deliberate; the generator's docstring says so and points at the originals.

---

### Task 1: Generator skeleton and section-level coverage

**Files:**
- Create: `scripts/generate_full_coverage_docs.py`
- Test: run the generator, compare its output through the pipeline

**Interfaces:**
- Produces: `build_v1(path)`, `build_v2(path)`, `main()`; module constants `V1_SECTIONS`, `V2_SECTIONS`.

- [ ] **Step 1: Write the generator's section data and body builder**

Create `scripts/generate_full_coverage_docs.py`:

```python
"""Generate FullCoverageDemo_v1.docx / _v2.docx.

The pair is built to produce every deterministic change type the analyzer can
emit. Run from the repository root:

    python scripts/generate_full_coverage_docs.py

The OOXML helpers below (text box, footnote reference, footnotes part) are
deliberate copies of the private helpers in backend/tests/test_extraction.py.
Importing private names from a test module into a script is fragile, and
lifting them into a shared module would churn a large green test file for no
behavioural gain.

Two things Word rejects, both guarded here:
  * a paragraph appended after <w:sectPr>, which must be the last child of
    <w:body> - use body.insert_element_before(p, "w:sectPr")
  * a <wp:inline> missing <wp:extent> or <wp:docPr>
"""

import os
import zipfile

from docx import Document
from docx.oxml.ns import qn
from lxml import etree

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "test-documents", "docx")

# Section layout. The insertion (2.0 Responsibilities, v2 only) sits ABOVE the
# cascade-affected sections and the deletion (Definitions) BELOW them, so the net
# shift for the cascade sections is exactly +1. Sections below the deletion cancel
# out and stay put. "9.0 Records" takes +2 against an expected +1, so it is
# reported as a deliberate renumber rather than a cascade.
V1_SECTIONS = [
    ("1.0 Purpose", [
        "This procedure describes tablet compression and release testing.",
        "It applies to all commercial batches manufactured at Site B.",
    ]),
    ("2.0 Scope", [
        "Covers in-process control, finished product testing, and release.",
        "Excludes stability testing, which is covered by SOP-QA-118.",
    ]),
    ("3.0 Equipment", [
        "Compression is performed on the rotary press listed below.",
    ]),
    ("4.0 Sampling", [
        "Samples are drawn at the start, middle, and end of each run.",
        "A retained sample of 30 tablets is held for each batch.",
        "Sampling tools are cleaned between batches.",
    ]),
    ("5.0 Procedure", [
        "Compression force shall be maintained at 18 kN plus or minus 2 kN.",
        "Record the force reading every 30 minutes during the run.",
    ]),
    ("6.0 Acceptance Criteria", [
        "Assay shall be 95.0 percent to 105.0 percent of label claim.",
    ]),
    ("7.0 Deviations", [
        "Deviations are recorded in the quality management system.",
    ]),
    ("8.0 Training", [
        "Operators are trained before independent operation.",
    ]),
    ("9.0 Records", [
        "Batch records are retained for seven years.",
    ]),
    ("10.0 Definitions", [
        "In-process control means testing performed during manufacture.",
        "Retained sample means material held for future examination.",
        "Release means the formal decision to make a batch available.",
    ]),
    ("11.0 Approval", [
        "This procedure is approved by the QC Manager.",
    ]),
    ("12.0 References", [
        "Refer to the equipment manual for calibration intervals.",
    ]),
]
```

Add `V2_SECTIONS` below it with these differences, and nothing else:

- **Insert** `"2.0 Responsibilities"` (2 paragraphs) at index 1, renumbering `2.0 Scope` onward.
- **Rename** `2.0 Scope` to `3.0 Applicability` — a substantial rewording, so section matching pairs it on body content and the confidence clause fires.
- **Delete** `10.0 Definitions` entirely (3 paragraphs + 1 table).
- **Cascade**: `3.0 Equipment` → `4.0 Equipment`, `4.0 Sampling` → `5.0 Sampling`, `6.0 Acceptance Criteria` → `7.0 Acceptance Criteria`, `7.0 Deviations` → `8.0 Deviations`, `8.0 Training` → `9.0 Training`. Each shifts exactly +1.
- **Deliberate renumber**: `9.0 Records` → `11.0 Records` (+2 against an expected +1).
- **Move**: `5.0 Procedure` relocates to after `Training`, becoming `10.0 Procedure`, **and** its compression force changes from `18 kN` to `20 kN`. This is the move-must-not-hide-an-edit case.
- **Content edits** in otherwise stable sections: add one paragraph to `1.0 Purpose` (`added_paragraph`); delete the third `4.0 Sampling` paragraph (`deleted_paragraph`); change `95.0 percent to 105.0 percent` to `98.0 percent to 102.0 percent` in Acceptance Criteria (`numeric_change`); change `seven years` to `ten years` in Records; change a date and a unit in `12.0 References` (`date_change`, `unit_change`).
- **Move a paragraph between sections**: the retained-sample sentence moves from `Sampling` to `Acceptance Criteria` (`moved_paragraph`).

- [ ] **Step 2: Add the body builder and `main`**

```python
def _add_sections(doc, sections):
    for heading, paragraphs in sections:
        doc.add_heading(heading, level=1)
        for text in paragraphs:
            doc.add_paragraph(text)


def build_v1(path):
    doc = Document()
    _add_sections(doc, V1_SECTIONS)
    doc.save(path)


def build_v2(path):
    doc = Document()
    _add_sections(doc, V2_SECTIONS)
    doc.save(path)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    build_v1(os.path.join(OUT_DIR, "FullCoverageDemo_v1.docx"))
    build_v2(os.path.join(OUT_DIR, "FullCoverageDemo_v2.docx"))
    print(f"wrote FullCoverageDemo_v1.docx and _v2.docx to {OUT_DIR}")


if __name__ == "__main__":
    main()
```

Tables, text boxes and footnotes are added in Tasks 2 and 3; `build_v1`/`build_v2` grow, their signatures do not.

- [ ] **Step 3: Run the generator and inspect the result**

```bash
python scripts/generate_full_coverage_docs.py
```

Then compare the pair through the pipeline with the classifier stubbed, and print the resulting `change_type` values with their old/new text. Confirm you see: `section_added`, `section_deleted`, `section_heading_changed`, `section_renumbered`, `section_renumbered_cascade`, `section_reordered`, `moved_paragraph`, `added_paragraph`, `deleted_paragraph`, `numeric_change`, `unit_change`, `date_change`.

**Confirm specifically** that at least one `section_renumbered_cascade` **and** at least one `section_renumbered` appear, and that the moved Procedure section yields **both** its move row and its `18 kN` → `20 kN` row. Expect roughly 6 cascades and 2 deliberate renumbers: the single insertion pushes every section below it by +1, so all of those cascade, while `Procedure` (+5, because it moved) and `Records` (+2) exceed the expected shift and stay deliberate. Do not adjust section numbers to reduce the cascade count — a high cascade count is the correct consequence of one insertion near the top. If the cascade row is missing, the insertion or deletion is on the wrong side of the affected sections — re-read the Prior Verification section rather than adjusting numbers at random.

- [ ] **Step 4: Open both files in Microsoft Word**

Both must open with no repair prompt. This cannot be automated.

- [ ] **Step 5: Commit**

```bash
git add scripts/generate_full_coverage_docs.py test-documents/docx/FullCoverageDemo_v1.docx test-documents/docx/FullCoverageDemo_v2.docx
git commit -m "test: add full-coverage demo generator with section-level changes"
```

---

### Task 2: Table coverage

**Files:**
- Modify: `scripts/generate_full_coverage_docs.py`

**Interfaces:**
- Produces: `_add_table(doc, rows)`; module constant `TABLES` describing each table's v1 and v2 form.

- [ ] **Step 1: Add the table builder**

```python
def _add_table(doc, rows, merge=None):
    """rows is a list of row lists. merge, when given, is (row, col_start, col_end)
    and merges those cells horizontally - the shape diff_merges reports."""
    table = doc.add_table(rows=len(rows), cols=len(rows[0]))
    table.style = "Table Grid"
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            table.cell(r, c).text = value
    if merge is not None:
        r, c0, c1 = merge
        table.cell(r, c0).merge(table.cell(r, c1))
    return table
```

- [ ] **Step 2: Define the eight single-purpose tables**

Each table lives in a named section and changes in exactly one way. Add a
`TABLES` constant mapping section heading to `(v1_rows, v2_rows, v1_merge, v2_merge)`:

| Table | Section | v1 → v2 |
|---|---|---|
| T1 | `3.0 Equipment` | row added |
| T2 | `4.0 Sampling` | row deleted |
| T3 | `6.0 Acceptance Criteria` | two rows swapped (`table_row_moved`) |
| T4 | `7.0 Deviations` | column added |
| T5 | `8.0 Training` | column deleted |
| T6 | `9.0 Records` | two columns swapped (`table_column_moved`) |
| T7 | `11.0 Approval` | two header cells merged in v2 only |
| T8 | `12.0 References` | one cell's text edited, no structural change |

`T8` is what produces `added_table_content` and `deleted_table_content`: those
per-cell rows are **suppressed** inside a structurally added or deleted row, so
they need a table with no structural change. `moved_table_content` comes from
`T3`, whose swapped rows relocate cell text between sections' table content.

The deleted section `10.0 Definitions` also carries a 3x3 table, so its summary
reads exactly `3 paragraphs, 1 table.`. The added section `2.0 Responsibilities`
carries one table so its summary names a table too.

Use realistic pharmaceutical content — parameter/limit/method columns, assay and
dissolution rows — so the fixture doubles as a demo.

- [ ] **Step 3: Regenerate and verify the table types**

Re-run the generator and re-compare. Confirm all seven table structure types plus
`added_table_content`, `deleted_table_content` and `moved_table_content` now
appear, and that the previously-verified section types are all still present.

**If a table produces two structural types instead of one**, the table is doing
too much — split it. A column change reshuffles row matching, which is exactly
the interaction this fixture is designed not to test.

- [ ] **Step 4: Open both files in Word**

Again, no repair prompt.

- [ ] **Step 5: Commit**

```bash
git add scripts/generate_full_coverage_docs.py test-documents/docx/FullCoverageDemo_v1.docx test-documents/docx/FullCoverageDemo_v2.docx
git commit -m "test: add table structure coverage to the full-coverage demo"
```

---

### Task 3: Text box and footnote coverage

**Files:**
- Modify: `scripts/generate_full_coverage_docs.py`

- [ ] **Step 1: Copy the OOXML helpers**

Copy `_DRAWINGML_TEXTBOX_XML`, `_paragraph_xml`, `_add_text_box`,
`_add_footnote_reference` and `_save_docx_with_footnotes` verbatim from
`backend/tests/test_extraction.py` into the generator, keeping their explanatory
docstrings and comments. Do **not** modify the originals.

The text box XML template there already contains the `<wp:extent>` and
`<wp:docPr>` elements Word requires — that is why it is copied rather than
rewritten.

- [ ] **Step 2: Anchor the text boxes correctly**

Add two text boxes, in **different** sections, so their labels differ by anchor
rather than only by ordinal:

- one in `5.0 Procedure` (v1) — which moves in v2, so its anchor changes
- one in `8.0 Training` (v1) / `9.0 Training` (v2)

`_add_text_box` ends with `container_element.append(p)`, which puts the
paragraph **after** `<w:sectPr>` when the container is the document body. That
is one of the two things Word rejects. Add a wrapper rather than editing the
copied helper, so the copy stays identical to its original:

```python
def _add_body_text_box(doc, paragraph_texts):
    # _add_text_box appends, which lands the paragraph after <w:sectPr>. sectPr
    # must be the LAST child of <w:body> or Word refuses to open the file, so
    # move the paragraph back in front of it.
    body = doc.element.body
    _add_text_box(body, paragraph_texts)
    paragraph = body[-1]
    body.remove(paragraph)
    body.insert_element_before(paragraph, "w:sectPr")
```

Use `_add_body_text_box` for both boxes. Verify by reading the saved file's
`word/document.xml` and confirming `<w:sectPr>` is the final child of
`<w:body>`.

- [ ] **Step 3: Anchor a footnote**

Add a footnote reference on the compression-force paragraph of `5.0 Procedure`,
then save with `_save_docx_with_footnotes`. Its label should name the Procedure
section and the paragraph it sits in, and the anchor should differ between v1 and
v2 because that section moves.

- [ ] **Step 4: Regenerate and verify anchoring**

Re-run the generator and extract both files with `app.extraction.extract_text`.
Confirm:

- the two text box labels carry **different** section anchors in the same document
- the footnote label names the Procedure section and a paragraph position
- every previously-verified change type is still produced

- [ ] **Step 5: Open both files in Word**

This is the step most likely to fail, because it is the step that introduces raw
drawing XML and a spliced footnotes part. If Word reports a problem, the cause is
almost certainly one of the two documented above.

- [ ] **Step 6: Commit**

```bash
git add scripts/generate_full_coverage_docs.py test-documents/docx/FullCoverageDemo_v1.docx test-documents/docx/FullCoverageDemo_v2.docx
git commit -m "test: add text box and footnote coverage to the full-coverage demo"
```

---

### Task 4: The regression test and expected-results table

**Files:**
- Create: `backend/tests/test_full_coverage_corpus.py`
- Create: `docs/full-coverage-demo-expected-results.md`

- [ ] **Step 1: Write the coverage test**

```python
import os

from app import llm_classifier, pipeline
from app.extraction import extract_text

_DOCS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "test-documents", "docx",
)

DETERMINISTIC_CHANGE_TYPES = {
    "numeric_change", "unit_change", "date_change",
    "section_added", "section_deleted", "section_heading_changed",
    "section_renumbered", "section_renumbered_cascade", "section_reordered",
    "moved_paragraph", "moved_table_content",
    "added_paragraph", "deleted_paragraph",
    "added_table_content", "deleted_table_content",
    "table_row_added", "table_row_deleted", "table_row_moved",
    "table_column_added", "table_column_deleted", "table_column_moved",
    "table_cell_merge_changed",
}


def _compare(monkeypatch):
    monkeypatch.setattr(llm_classifier, "classify_changes_batch", lambda items, *a, **k: [])
    old = extract_text(os.path.join(_DOCS, "FullCoverageDemo_v1.docx"), "docx")
    new = extract_text(os.path.join(_DOCS, "FullCoverageDemo_v2.docx"), "docx")
    return pipeline.compare_documents(old, new, "FullCoverageDemo_v1.docx", "FullCoverageDemo_v2.docx")


def test_full_coverage_pair_produces_every_deterministic_change_type(monkeypatch):
    result = _compare(monkeypatch)

    produced = {c.change_type for c in result.changes}
    missing = DETERMINISTIC_CHANGE_TYPES - produced

    assert not missing, f"not produced by the fixture: {sorted(missing)}"


def test_moved_section_still_reports_its_content_edit(monkeypatch):
    # The central false-negative guard: relocation must never hide an edit.
    result = _compare(monkeypatch)

    assert any(c.change_type == "section_reordered" for c in result.changes)
    assert any("20 kN" in (c.new_text or "") for c in result.changes)


def test_cascading_and_deliberate_renumbering_are_distinguished(monkeypatch):
    result = _compare(monkeypatch)

    cascaded = [c for c in result.changes if c.change_type == "section_renumbered_cascade"]
    deliberate = [c for c in result.changes if c.change_type == "section_renumbered"]

    assert cascaded, "no cascade produced - check the insertion is above and the deletion below"
    assert deliberate, "no deliberate renumber produced"


def test_structural_summary_counts_are_all_non_zero(monkeypatch):
    result = _compare(monkeypatch)
    s = result.summary

    assert s.sections_added > 0
    assert s.sections_deleted > 0
    assert s.sections_renamed > 0
    assert s.sections_renumbered > 0
    assert s.sections_cascaded > 0
    assert s.sections_moved > 0


def test_text_box_and_footnote_labels_carry_their_location(monkeypatch):
    old = extract_text(os.path.join(_DOCS, "FullCoverageDemo_v1.docx"), "docx")
    labels = [p.text for p in old if p.is_heading and
              (p.text.startswith("Text Box") or p.text.startswith("Footnote"))]

    text_box_anchors = {label.split("(", 1)[1] for label in labels if label.startswith("Text Box")}

    assert len(text_box_anchors) == 2, f"text boxes must anchor to different sections: {labels}"
    assert any(label.startswith("Footnote") and "(" in label for label in labels)
```

- [ ] **Step 2: Run the test**

Run: `cd backend && python -m pytest tests/test_full_coverage_corpus.py -v`
Expected: all pass. A failure names exactly which change type the fixture does not produce.

- [ ] **Step 3: Run both full suites**

Run: `cd backend && python -m pytest -q` and `cd frontend && python -m pytest -q`
Expected: 353 + 5 backend, 85 frontend. No existing test may change — the pair is additive.

- [ ] **Step 4: Write the expected-results table**

Create `docs/full-coverage-demo-expected-results.md`: a table of every row the
comparison produces, with columns Section, Change Type, Old Text, New Text,
Risk, and what the row demonstrates. Generate it by running the comparison and
transcribing actual output — do **not** hand-write predictions.

Add a final section listing the 6 LLM-derived types, each with the sentence
written to invite it, marked **"LLM-dependent, not asserted"** and noting that
the observed label may differ between runs and model versions.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/test_full_coverage_corpus.py docs/full-coverage-demo-expected-results.md
git commit -m "test: assert full deterministic change-type coverage"
```
