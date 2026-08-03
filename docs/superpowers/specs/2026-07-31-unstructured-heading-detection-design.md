# Replace DOCX/PDF Heading Detection with `unstructured` — Design

**Status:** Approved for implementation

## Purpose

The current DOCX heading detection (Word paragraph style name starting with
`"Heading"`/`"Title"`) and PDF heading detection (exact match against the
file's embedded table of contents) both miss a common real-world case:
headings distinguished only by visual formatting — larger font size, bold —
with no Word style applied and no page numbering in the source PDF. The
end goal is that section detection works correctly regardless of which
formatting convention a given document happens to use.

Two related issues motivated this specifically:
1. A real bug found during edge-case testing: when a document has a mix of
   "properly" signaled headings (styled, or in the TOC) and headings that
   aren't, the unsignaled ones get silently swallowed into whichever
   section precedes them — not just missed, but silently wrong, since it's
   the *combination* of "some signal exists in this document" and
   "per-document fallback logic" that causes the swallowing (see
   `sectioning.py`'s layered detection: once any paragraph has a
   structural signal, the text-pattern fallback never runs for the rest
   of the document).
2. Font-size-only headings, with no numbering and no Word style, aren't
   detected by either the structural signal or the text-pattern fallback
   at all — they fall to the last-resort one-paragraph-per-section case.

Note: this is an incremental improvement to the *detection signal itself*,
not a change to section *matching* — matching is already purely
embedding-based cosine similarity and is already agnostic to how sections
were detected. Detection quality only affects section boundary accuracy
and how finely content gets grouped for matching, not the matching
mechanism.

Also worth being explicit about: no deterministic heuristic system,
including `unstructured`'s, can guarantee correct detection for literally
any possible formatting convention (e.g. color-only or centered-text-only
conventions with no size/style/numbering signal would still slip past
it). This closes the realistic majority of the gap, not the theoretical
totality of it.

## Decision

Adopt the `unstructured` library (Apache 2.0) for DOCX and PDF heading
detection, replacing the current hand-rolled style-name and TOC-matching
logic entirely. TXT stays on its current regex-based text-pattern
detection — plain text carries no formatting signal `unstructured` could
exploit beyond what the existing heuristic already does, and this keeps
the already-well-handled simplest format's code path unchanged and
untouched by this migration.

**PDF strategy: `"fast"`** — rule-based (font size, position, whitespace),
not `unstructured`'s `"hi_res"` computer-vision layout model. `"fast"`
needs no ML/CV dependencies, keeping the install and runtime memory
footprint far smaller — a real consideration given Streamlit Community
Cloud's free-tier memory constraints, even though this project hasn't
concretely hit a memory wall there yet (a proactive precaution, not a
response to an observed failure).

## Scope of Change

**`backend/app/extraction.py`:** PDF and DOCX extraction both route
through `unstructured.partition.auto.partition(filename, strategy="fast")`
(the `strategy` argument only affects PDF; DOCX partitioning ignores it).
This returns a list of `Element` objects, each with `.category` (`"Title"`,
`"NarrativeText"`, `"ListItem"`, `"Table"`, etc.), `.text`, and — for PDF
only — `.metadata.page_number`. Each `Element` maps to a `Paragraph`:
`is_heading = (element.category == "Title")`, `text = element.text`,
`page = element.metadata.page_number` (PDF) or `None` (DOCX),
`paragraph_index` assigned sequentially (DOCX) or left `None` (PDF, same
as current behavior — PDF paragraphs are identified by page, not index).

This fully replaces the current `HEADING_STYLE_PREFIXES` check (DOCX) and
`page_toc_titles` matching (PDF) — `unstructured`'s own heuristics become
the sole Layer 1 signal for these two formats. `_extract_txt` is
untouched.

**`backend/app/sectioning.py`:** unchanged. The three-layer fallback
(structural signal → text-pattern regex → one-paragraph-per-section) stays
exactly as it is — cheap insurance regardless of how good the Layer 1
signal is, and `unstructured`'s Title detection just becomes a stronger,
broader version of that same Layer 1 signal for DOCX/PDF.

**Dependency:** `unstructured[docx]` and `unstructured[pdf]` added to
`backend/requirements.txt` (and the merged `frontend/requirements.txt`
used for the Streamlit Cloud deployment). The `"fast"` PDF strategy pulls
in `pdfminer.six` for text-layer extraction — no CV/ML models.

## Testing

The existing DOCX/PDF tests in `backend/tests/test_extraction.py` assert
behavior tied to the *old* style-name/TOC logic (e.g.
`test_extract_docx_tags_heading_style_paragraphs`,
`test_extract_pdf_tags_toc_entries_as_headings`) — these get rewritten to
construct fixtures and assert against `unstructured`-based behavior
instead. New test coverage specifically targets the capability that
motivated this change: a DOCX heading distinguished only by font
size/bold (no Word style applied, no numbering) and a PDF heading
distinguished only by font size (no embedded TOC, no numbering) both
correctly get `is_heading=True`.

Full backend suite (currently 63 tests) re-run after the migration to
confirm no regression in the downstream stages (sectioning, section
matching, diffing, pipeline) that consume `Paragraph` objects, since this
changes what those stages receive as input for DOCX/PDF specifically.

## Out of Scope

- TXT extraction — stays on the current regex-based approach.
- OCR/scanned PDFs — still unsupported; `unstructured`'s OCR mode is not
  being used, keeping the same phase-2 boundary as before.
- `hi_res` PDF strategy — not adopted now; could be revisited later if
  `"fast"` proves insufficient on real-world documents and the memory
  trade-off becomes worth it.
