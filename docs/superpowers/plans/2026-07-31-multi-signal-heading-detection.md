# Multi-Signal Heading Detection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix a real bug (structural heading signal in one part of a document silently blocks text-pattern heading detection elsewhere) and close two real gaps (ALL-CAPS headings with no numbering, font-size-only headings with no Word style/TOC) in the pipeline's heading detection, using only already-installed libraries.

**Architecture:** Four detection signals combined with OR, evaluated per paragraph instead of as a sequential fallback. Two signals (structural: DOCX style / PDF TOC; font-size: DOCX/PDF only) are resolved during extraction and collapse into the existing `Paragraph.is_heading` field. Two signals (numbered text pattern; ALL CAPS) are format-agnostic and live in `sectioning.py`, evaluated regardless of what extraction found. PDF's font-size support requires rebuilding `_extract_pdf` around PyMuPDF's structured `"dict"` text mode, replacing the current plain-text-mode extraction — verified empirically (real fixtures, actual output) to correctly preserve every existing PDF extraction behavior (TOC-matched heading separation, wrapped multi-line paragraphs staying as one paragraph, page numbering) while adding font-size data the old approach couldn't provide.

**Tech Stack:** Python, `python-docx`, PyMuPDF (`fitz`) — no new dependencies.

## Global Constraints

- No new dependencies. `unstructured` was evaluated and rejected (see the design doc's superseded-spec note) — do not reintroduce it.
- `Paragraph.is_heading` remains the single field both extraction-resolved signals (structural, font-size) combine into — no new fields on `Paragraph`.
- The font-size heading threshold is a fixed value: **2.0pt above the document's body baseline**, for both DOCX and PDF.
- DOCX body baseline: `document.styles["Normal"].font.size` if resolvable, otherwise a hardcoded **11.0pt** fallback — never "most common resolved size across paragraphs" (empirically shown to skew toward heading sizes, not body sizes, since body text mostly doesn't resolve at all).
- PDF body baseline: the most common font size across every extracted block in the document — this DOES work reliably for PDF (unlike DOCX), since every PyMuPDF span always reports a concrete rendered size with no inheritance ambiguity.
- Every font-size or ALL-CAPS heading candidate must also pass the existing shape constraints: ≤120 characters, ≤12 words, does not end in `.`, `,`, or `;`.
- All three existing PDF extraction tests (`test_extract_pdf_tags_page_numbers`, `test_extract_pdf_tags_toc_entries_as_headings`, `test_extract_pdf_preserves_wrapped_paragraphs_without_toc`) must continue to pass, unmodified, against the rebuilt `_extract_pdf`.

---

### Task 1: Fix the sectioning swallowing bug and add ALL-CAPS heading detection

**Files:**
- Modify: `backend/app/sectioning.py`
- Test: `backend/tests/test_sectioning.py`

**Interfaces:**
- Consumes: `app.models.Paragraph`, `Section` (unchanged)
- Produces: `app.sectioning.split_into_sections(paragraphs: list[Paragraph]) -> list[Section]` — same signature as before, but now evaluates every detection signal per paragraph independently instead of as a sequential fallback. `app.sectioning._looks_like_heading_shape(text: str) -> bool` — new, reusable shape-constraint helper (extracted from the existing numbered-heading check), used by both the new ALL-CAPS check here and the new font-size checks in Tasks 2/3.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_sectioning.py` (the existing 5 tests in this file stay unchanged — these are additions):

```python
def test_structural_signal_does_not_block_numbered_pattern_elsewhere():
    paragraphs = [
        Paragraph(text="Introduction", is_heading=True),
        Paragraph(text="This document describes the procedure."),
        Paragraph(text="5.2 Sample Preparation"),
        Paragraph(text="Weigh 10 mg of sample."),
    ]

    sections = split_into_sections(paragraphs)

    assert len(sections) == 2
    assert sections[0].heading == "Introduction"
    assert sections[1].heading == "5.2 Sample Preparation"


def test_all_caps_heading_without_numbering_is_detected():
    paragraphs = [
        Paragraph(text="SCOPE"),
        Paragraph(text="This procedure applies to all lab testing."),
        Paragraph(text="MATERIALS AND METHODS"),
        Paragraph(text="Use validated equipment only."),
    ]

    sections = split_into_sections(paragraphs)

    assert len(sections) == 2
    assert sections[0].heading == "SCOPE"
    assert sections[1].heading == "MATERIALS AND METHODS"


def test_all_caps_sentence_ending_in_period_is_not_a_heading():
    paragraphs = [
        Paragraph(text="1.0 Warnings"),
        Paragraph(text="DO NOT USE IF SEAL IS BROKEN."),
    ]

    sections = split_into_sections(paragraphs)

    assert len(sections) == 1
    assert sections[0].heading == "1.0 Warnings"
    assert [p.text for p in sections[0].paragraphs] == ["DO NOT USE IF SEAL IS BROKEN."]
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `backend/`): `pytest tests/test_sectioning.py -v`
Expected: FAIL — `test_structural_signal_does_not_block_numbered_pattern_elsewhere` fails because the current sequential-fallback logic swallows "5.2 Sample Preparation" into the "Introduction" section (only 1 section produced, not 2). `test_all_caps_heading_without_numbering_is_detected` fails because there is no ALL-CAPS detection at all yet (produces 1 fallback section per paragraph, 4 sections, not 2).

- [ ] **Step 3: Rewrite `backend/app/sectioning.py`**

Replace the file's contents with:

```python
import re

from app.models import Paragraph, Section

HEADING_NUMBER_PATTERN = re.compile(r"^\s*\d+(\.\d+)+\s+\S.*$")
MAX_HEADING_LENGTH = 120
MAX_HEADING_WORDS = 12


def _looks_like_heading_shape(text: str) -> bool:
    if len(text) > MAX_HEADING_LENGTH:
        return False
    if len(text.split()) > MAX_HEADING_WORDS:
        return False
    if text.rstrip().endswith((".", ",", ";")):
        return False
    return True


def _looks_like_numbered_heading(text: str) -> bool:
    return bool(HEADING_NUMBER_PATTERN.match(text)) and _looks_like_heading_shape(text)


def _looks_like_all_caps_heading(text: str) -> bool:
    return text.isupper() and _looks_like_heading_shape(text)


def _is_heading_paragraph(p: Paragraph) -> bool:
    if p.is_heading:
        return True
    if _looks_like_numbered_heading(p.text):
        return True
    if _looks_like_all_caps_heading(p.text):
        return True
    return False


def split_into_sections(paragraphs: list[Paragraph]) -> list[Section]:
    heading_indices = [i for i, p in enumerate(paragraphs) if _is_heading_paragraph(p)]

    if not heading_indices:
        return [
            Section(heading=f"Paragraph {i + 1}", paragraphs=[p])
            for i, p in enumerate(paragraphs)
        ]

    sections: list[Section] = []
    if heading_indices[0] > 0:
        sections.append(Section(heading="Preamble", paragraphs=paragraphs[: heading_indices[0]]))

    for idx, start in enumerate(heading_indices):
        end = heading_indices[idx + 1] if idx + 1 < len(heading_indices) else len(paragraphs)
        heading_text = paragraphs[start].text
        body = paragraphs[start + 1 : end]
        sections.append(Section(heading=heading_text, paragraphs=body))

    return sections
```

- [ ] **Step 4: Run the full sectioning test suite to verify everything passes**

Run: `pytest tests/test_sectioning.py -v`
Expected: PASS (8 tests — the 5 existing ones plus the 3 new ones added in Step 1)

- [ ] **Step 5: Run the full backend suite to confirm no regression**

Run (from `backend/`): `pytest -v`
Expected: PASS (all tests — this changes shared code every downstream stage consumes, so a full run matters here)

- [ ] **Step 6: Commit**

```bash
git add backend/app/sectioning.py backend/tests/test_sectioning.py
git commit -m "fix: evaluate heading signals per-paragraph, add ALL-CAPS detection"
```

---

### Task 2: DOCX font-size heading detection

**Files:**
- Modify: `backend/app/extraction.py`
- Test: `backend/tests/test_extraction.py`

**Interfaces:**
- Consumes: `app.sectioning._looks_like_heading_shape` (Task 1) — reused here so the shape constraint (length/word-count/no-trailing-punctuation) is identical between the ALL-CAPS check and the font-size check, not two independently-drifting copies.
- Produces: no change to `app.extraction.extract_text`'s public signature. `Paragraph.is_heading` for DOCX now also fires from font size, in addition to the existing Word-style check.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_extraction.py` (import `Pt` from `docx.shared` at the top of the file alongside the existing imports):

```python
from docx.shared import Pt


def test_extract_docx_tags_font_size_only_heading(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    doc.add_paragraph("Weigh 10 mg of sample and dilute to volume.")
    p = doc.add_paragraph()
    run = p.add_run("Sample Preparation")
    run.bold = True
    run.font.size = Pt(16)
    doc.add_paragraph("Inject into the HPLC system.")
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")

    heading_paragraphs = [p for p in paragraphs if p.is_heading]
    assert len(heading_paragraphs) == 1
    assert heading_paragraphs[0].text == "Sample Preparation"


def test_extract_docx_does_not_flag_normal_body_text_as_heading(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    doc.add_paragraph("This is a completely normal paragraph with no special formatting at all.")
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")

    assert all(not p.is_heading for p in paragraphs)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_extraction.py::test_extract_docx_tags_font_size_only_heading -v`
Expected: FAIL — the font-size-only "Sample Preparation" paragraph has no Word style, so `is_heading` is currently `False`, but the test expects it to be the one and only heading.

- [ ] **Step 3: Update `backend/app/extraction.py`**

Add these constants and functions near the top of the file (alongside `HEADING_STYLE_PREFIXES`):

```python
from app.sectioning import _looks_like_heading_shape

DOCX_DEFAULT_BODY_SIZE_PT = 11.0
DOCX_HEADING_SIZE_DELTA_PT = 2.0


def _docx_paragraph_font_size_pt(para) -> float | None:
    if para.runs and para.runs[0].font.size is not None:
        return para.runs[0].font.size.pt
    if para.style and para.style.font.size is not None:
        return para.style.font.size.pt
    return None


def _docx_body_baseline_pt(doc) -> float:
    normal_size = doc.styles["Normal"].font.size
    if normal_size is not None:
        return normal_size.pt
    return DOCX_DEFAULT_BODY_SIZE_PT
```

Replace `_extract_docx` with:

```python
def _extract_docx(file_path: str) -> list[Paragraph]:
    doc = DocxDocument(file_path)
    baseline_pt = _docx_body_baseline_pt(doc)

    paragraphs: list[Paragraph] = []
    index = 0
    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        style_name = para.style.name if para.style else ""
        is_heading_style = style_name.startswith(HEADING_STYLE_PREFIXES)

        size_pt = _docx_paragraph_font_size_pt(para)
        is_heading_size = (
            size_pt is not None
            and size_pt >= baseline_pt + DOCX_HEADING_SIZE_DELTA_PT
            and _looks_like_heading_shape(text)
        )

        paragraphs.append(
            Paragraph(
                text=text,
                paragraph_index=index,
                is_heading=is_heading_style or is_heading_size,
            )
        )
        index += 1
    return paragraphs
```

- [ ] **Step 4: Run the new tests and the full extraction suite to verify they pass**

Run: `pytest tests/test_extraction.py -v`
Expected: PASS (all existing extraction tests plus the 2 new ones)

- [ ] **Step 5: Run the full backend suite to confirm no regression**

Run (from `backend/`): `pytest -v`
Expected: PASS (all tests)

- [ ] **Step 6: Commit**

```bash
git add backend/app/extraction.py backend/tests/test_extraction.py
git commit -m "feat: detect DOCX headings distinguished only by font size"
```

---

### Task 3: Rebuild PDF extraction around dict-mode, add font-size heading detection

**Files:**
- Modify: `backend/app/extraction.py`
- Test: `backend/tests/test_extraction.py`

**Interfaces:**
- Consumes: `app.sectioning._looks_like_heading_shape` (Task 1), same as Task 2.
- Produces: no change to `app.extraction.extract_text`'s public signature or to `Paragraph`'s fields. `_extract_pdf`'s internals are fully replaced — it now derives paragraphs from PyMuPDF's `"dict"` text mode instead of plain-text mode — but its observable behavior (page numbers, is_heading from TOC matches, wrapped multi-line paragraphs staying as one `Paragraph`) is unchanged, verified against the three existing PDF tests below plus two new font-size tests.

**Context for whoever implements this:** the previous approach (keep plain-text extraction untouched, correlate a second dict-mode pass by paragraph order) was tested against a real fixture during planning and found broken — PyMuPDF's plain-text mode can merge multiple dict-mode blocks into a single paragraph (joined by `\n`, not `\n\n`), so the two passes don't reliably produce the same number of paragraphs to line up by position. This task replaces `_extract_pdf` entirely instead. This was verified during planning against the exact fixtures the three existing PDF tests use, confirming dict-mode blocks correctly separate a TOC-matched heading from adjacent body text, and correctly keep a genuinely wrapped multi-line paragraph as one block — do not re-litigate that design decision, implement as specified below.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_extraction.py`:

```python
def test_extract_pdf_tags_font_size_only_heading(tmp_path):
    file_path = tmp_path / "doc.pdf"
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "1.0 Scope", fontsize=11)
    page.insert_text((72, 100), "This procedure applies to all testing in the QC lab.", fontsize=11)
    page.insert_text((72, 140), "Sample Preparation", fontsize=18)
    page.insert_text((72, 165), "Weigh 10 mg of sample and dilute to volume with mobile phase.", fontsize=11)
    pdf.save(str(file_path))
    pdf.close()

    paragraphs = extract_text(str(file_path), "pdf")

    heading_texts = {p.text for p in paragraphs if p.is_heading}
    assert heading_texts == {"1.0 Scope", "Sample Preparation"}


def test_extract_pdf_does_not_flag_normal_body_text_as_heading(tmp_path):
    file_path = tmp_path / "doc.pdf"
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "This is a completely normal sentence with no special formatting.", fontsize=11)
    pdf.save(str(file_path))
    pdf.close()

    paragraphs = extract_text(str(file_path), "pdf")

    assert all(not p.is_heading for p in paragraphs)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_extraction.py::test_extract_pdf_tags_font_size_only_heading -v`
Expected: FAIL — the current plain-text-based `_extract_pdf` has no font-size data at all, so the 18pt "Sample Preparation" paragraph isn't flagged as a heading.

- [ ] **Step 3: Replace `_extract_pdf` in `backend/app/extraction.py`**

Add `import collections` to the file's existing top-of-file import block
(alongside `import fitz` and the others already there). Then add these
constants and helper functions (alongside the DOCX ones from Task 2):

```python
PDF_HEADING_SIZE_DELTA_PT = 2.0


def _pdf_block_text(block: dict) -> str:
    line_texts = []
    for line in block["lines"]:
        line_texts.append("".join(span["text"] for span in line["spans"]))
    return " ".join(line_texts).strip()


def _pdf_block_size(block: dict) -> float | None:
    for line in block["lines"]:
        for span in line["spans"]:
            return span["size"]
    return None


def _pdf_body_baseline_pt(sizes: list[float]) -> float | None:
    if not sizes:
        return None
    return collections.Counter(sizes).most_common(1)[0][0]
```

Replace the existing `_extract_pdf` function entirely with:

```python
def _extract_pdf(file_path: str) -> list[Paragraph]:
    doc = fitz.open(file_path)

    toc_titles_by_page: dict[int, set[str]] = {}
    for _level, title, page_number in doc.get_toc():
        toc_titles_by_page.setdefault(page_number, set()).add(title.strip())

    raw_blocks: list[tuple[str, int, float | None]] = []
    for page_index, page in enumerate(doc):
        page_number = page_index + 1
        page_dict = page.get_text("dict")
        for block in page_dict["blocks"]:
            if "lines" not in block:
                continue
            block_text = _pdf_block_text(block)
            if block_text:
                raw_blocks.append((block_text, page_number, _pdf_block_size(block)))
    doc.close()

    baseline_pt = _pdf_body_baseline_pt([size for _, _, size in raw_blocks if size is not None])

    paragraphs: list[Paragraph] = []
    for text, page_number, size in raw_blocks:
        page_toc_titles = toc_titles_by_page.get(page_number, set())
        is_heading_toc = text in page_toc_titles
        is_heading_size = (
            baseline_pt is not None
            and size is not None
            and size >= baseline_pt + PDF_HEADING_SIZE_DELTA_PT
            and _looks_like_heading_shape(text)
        )
        paragraphs.append(
            Paragraph(text=text, page=page_number, is_heading=is_heading_toc or is_heading_size)
        )
    return paragraphs
```

- [ ] **Step 4: Run the new tests and the three pre-existing PDF tests to verify they all pass**

Run: `pytest tests/test_extraction.py -v -k pdf`
Expected: PASS — this must include `test_extract_pdf_tags_page_numbers`, `test_extract_pdf_tags_toc_entries_as_headings`, and `test_extract_pdf_preserves_wrapped_paragraphs_without_toc` (all pre-existing, unmodified) alongside the 2 new tests from Step 1. If any pre-existing test fails, do not weaken its assertions to make it pass — the whole point of this task is that the rebuild preserves this exact behavior; a failure here means the implementation has a real bug, not that the test is wrong.

- [ ] **Step 5: Run the full extraction suite and the full backend suite**

Run: `pytest tests/test_extraction.py -v`
Expected: PASS (all extraction tests, DOCX and PDF and TXT)

Run (from `backend/`): `pytest -v`
Expected: PASS (all tests — PDF paragraph granularity changing, even if behaviorally equivalent for existing cases, is exactly the kind of change that could surface a downstream surprise in sectioning/matching/pipeline tests)

- [ ] **Step 6: Commit**

```bash
git add backend/app/extraction.py backend/tests/test_extraction.py
git commit -m "feat: rebuild PDF extraction around dict-mode, add font-size heading detection"
```
