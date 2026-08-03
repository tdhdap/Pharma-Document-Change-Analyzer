# DOCX/PDF Test Document Generation — Design

**Status:** Approved for implementation

## Purpose

The existing `test-documents/` set (`A`, `B`, `C1`, `C2`, `SOP`, each as a
`v1`/`v2` TXT pair) was used to stress-test the change-detection pipeline,
but TXT carries no formatting signal — it can't exercise anything the
`2026-07-31-multi-signal-heading-detection` plan just built (DOCX font-size
detection, the rebuilt PDF dict-mode extraction, ALL-CAPS detection, or the
swallowing-bug fix for mixed structural/text-pattern signals).

This spec covers generating real DOCX and PDF equivalents of the same 5
scenarios, so they can be:
1. Manually uploaded and compared against the known TXT results, confirming
   the pipeline behaves consistently across formats for the same content.
2. Used to specifically probe each heading-detection signal in isolation,
   since each scenario is deliberately assigned a different signal to rely
   on for its headings (see below) — a document only proves a signal works
   if it can't pass without that signal.

## Decision

Reuse the exact section text/content from each existing TXT pair
unchanged, and generate a DOCX and a PDF version of each scenario's v1/v2
pair, with each scenario assigned one heading-detection convention to
isolate:

| Scenario | Content already tests | Heading signal isolated |
|---|---|---|
| **A** | Numeric-only value changes, no structural change | Word style (DOCX) / embedded TOC (PDF) — the pre-existing structural signal |
| **B** | Wording/reason changes, no structural change | ALL-CAPS, numbering prefix stripped from heading text (e.g. "RECORD RETENTION") so the numbered-pattern signal can't also fire |
| **C1 / C2** | Heavy renumbering, reordering, duplicate heading text, section add/remove | Mixed — headings alternate between Word-style and plain-numbered-text-only within the same document — the exact shape of the swallowing bug the multi-signal plan fixed |
| **SOP** | Full realistic SOP, many section adds/renumbers/wording edits | Font-size only — numbering prefix stripped, no Word style, headings distinguished purely by a larger font |

Stripping the numbering prefix where a scenario is meant to isolate
ALL-CAPS or font-size is deliberate: leaving "1.0 Record Retention" would
let the pre-existing numbered-pattern signal catch the heading regardless
of whether the new signal works at all, defeating the point of using that
scenario to prove the new signal — the same lesson the review process
already surfaced twice during the heading-detection plan (a test must be
unable to pass without the thing it claims to test).

## File Layout

```
test-documents/
  docx/
    A_v1.docx    A_v2.docx
    B_v1.docx    B_v2.docx
    C1_v1.docx   C1_v2.docx
    C2_v1.docx   C2_v2.docx
    SOP_v1.docx  SOP_v2.docx
  pdf/
    A_v1.pdf     A_v2.pdf
    B_v1.pdf     B_v2.pdf
    C1_v1.pdf    C1_v2.pdf
    C2_v1.pdf    C2_v2.pdf
    SOP_v1.pdf   SOP_v2.pdf
```

20 files total, matching the existing TXT naming so the same scenario is
identifiable across all three formats.

## Generation Mechanics

**PDF** (PyMuPDF/`fitz`), mirroring exactly what
`backend/tests/test_extraction.py`'s existing PDF fixtures already verify
empirically — no new assumptions about PyMuPDF's block-splitting behavior:

- Each heading or body line is its own `page.insert_text((x, y), text,
  fontsize=N)` call, spaced ≥28pt apart vertically — confirmed by the
  existing test suite to land as separate dict-mode blocks.
- A body paragraph that must survive as one `Paragraph` after wrapping uses
  a single `insert_text` call with embedded `\n` between its lines —
  confirmed to stay one block (`test_extract_pdf_preserves_wrapped_paragraphs_without_toc`).
- Scenario A's structural signal: `pdf.set_toc([[1, title, page_number],
  ...])` for every heading, matching `test_extract_pdf_tags_toc_entries_as_headings`.
- SOP's font-size headings: `fontsize=16` against `fontsize=11` body text —
  the same 5pt margin already proven safely above the 13pt threshold in
  `test_extract_pdf_tags_font_size_only_heading`.
- The generator tracks a running y-cursor per page and starts a new PyMuPDF
  page once it runs past the usable page height, so longer scenarios
  naturally span multiple pages — incidentally exercising page-number
  tagging too.

**DOCX** (`python-docx`):

- Body paragraphs: plain `doc.add_paragraph(text)` — no explicit run or
  style size, resolving to `None` and falling back to the hardcoded 11.0pt
  baseline, same as a realistic default Word document.
- Scenario A headings: `doc.add_paragraph(text, style="Heading 1")`.
- Scenario B headings: plain paragraph, ALL-CAPS text, no style, no
  explicit size.
- SOP headings: explicit `run.font.size = Pt(16)`, no style, no numbering
  prefix.
- C1/C2 headings: alternate between `style="Heading 1"` and a plain
  paragraph carrying only the numbered text, deliberately interleaved
  section-to-section.

## Script

One script, `scripts/generate_test_documents.py`. Each scenario's heading/
body text is defined once as shared data; a small per-format writer
function applies that scenario's assigned convention (structural /
ALL-CAPS / mixed / font-size) when emitting the DOCX and PDF files. Running
the script regenerates all 20 files idempotently — safe to re-run after
a content tweak.

## Validation

After generation, each pair is run through the real backend pipeline
(`extract_text` → `split_into_sections`) as a sanity check: confirming the
intended headings are detected and nothing else is, before handoff — so a
construction mistake is caught here, not during manual testing.

## Out of Scope

- PDF header/footer-as-heading behavior (a known, already-accepted minor
  finding from the heading-detection plan's final review) — not
  deliberately constructed into any of these fixtures.
- New content/scenarios beyond the existing 5 — this only translates
  known TXT scenarios into DOCX/PDF, it doesn't add new change-detection
  cases.
- Any change to application code — this is test-fixture generation only.
