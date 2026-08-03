# Multi-Signal Heading Detection — Design

**Status:** Approved for implementation

**Supersedes:** `2026-07-31-unstructured-heading-detection-design.md`. That
spec proposed adopting the `unstructured` library for DOCX/PDF heading
detection. Empirical testing (real fixtures, actual measured behavior, not
assumption) found: it costs +365MB of RSS memory just from importing the
partitioners (before processing anything), regardless of PDF strategy; its
DOCX partitioner does not detect font-size-only headings under either
strategy (`hi_res`'s `strategy` argument is silently ignored for DOCX,
since DOCX is never rendered to images); its PDF `"fast"` strategy does
detect font-size headings but also produced a false positive, tagging a
plain body sentence as a heading in the same test; and `"hi_res"` requires
Tesseract OCR, a system-level binary not installed here and not
`pip install`-able. Given no benefit for DOCX, a new failure mode for PDF,
and a real memory/dependency cost, this spec replaces that approach with a
self-built solution using only already-installed libraries.

## Purpose

Current heading detection has two real problems, found via testing:

1. **The "swallowing" bug.** `sectioning.py` treats structural signal
   (DOCX style match / PDF TOC match) and the numbered-text-pattern regex
   as a *sequential* fallback: if even one paragraph anywhere in the
   document has a structural signal, the text-pattern check never runs for
   the rest of the document. A document with some properly-styled headings
   and some plain numbered-but-unstyled headings silently merges the
   latter into whichever section precedes them.
2. **No detection for font-size-only or ALL-CAPS headings.** A heading
   distinguished only by a larger font (no Word style, no numbering) or by
   being written in all capitals (no numbering) isn't detected by any
   current signal, falling all the way to the one-paragraph-per-section
   last resort.

Same caveat as before: no fixed set of signals guarantees detection for
literally any convention (centered-only, color-only, font-family-only text
still won't be caught) — this closes the realistic majority of real-world
cases, not the theoretical totality.

## Decision

Combine four signals with OR, evaluated per paragraph (not sequential
fallback):

1. **Structural signal** (existing, format-specific) — DOCX Word style
   match, PDF embedded TOC match.
2. **Numbered text pattern** (existing, format-agnostic) — unchanged
   regex/length/word-count/punctuation rule, now evaluated on every
   paragraph regardless of what signal 1 found elsewhere in the document.
3. **NEW — ALL CAPS text pattern** (format-agnostic) — a short,
   fully-uppercase line with no trailing sentence punctuation. Lives in
   `sectioning.py`, which is shared by all three formats — this improves
   TXT too as a free side effect, even though TXT extraction itself isn't
   being touched.
4. **NEW — Font size** (format-specific, DOCX and PDF only) — a paragraph
   whose resolved font size is meaningfully larger than the document's own
   "body" baseline, combined with the same short-line/no-trailing-
   punctuation constraint as the numbered check, to avoid flagging a long
   body paragraph that happens to use a slightly larger font.

**Explicitly out of scope for this pass:** bold-as-the-only-signal (same
size as body), centered/color/font-family-only headings, multi-column PDF
reading order. Bold-without-a-size-difference is left out specifically to
keep the false-positive risk down — size difference is a stronger,
less ambiguous signal than boldness alone.

## Design per component

### `backend/app/sectioning.py`

Signals 1 and 4 (structural + font size) are resolved during extraction
and both already collapse into the existing `Paragraph.is_heading` field —
extraction.py becomes responsible for combining them, so sectioning.py
doesn't need to know the difference between "styled" and "large font."
Sectioning's job is to OR that field with the two new format-agnostic
text-pattern checks:

```python
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
    # ... rest unchanged: preamble handling, section grouping, one-per-paragraph fallback
```

This directly fixes the swallowing bug: `heading_indices` is now built from
every paragraph independently, so a document with one Word-styled heading
and one plain-numbered heading elsewhere correctly finds both, instead of
the structural hit blocking the text-pattern check for the rest of the
document.

`_looks_like_all_caps_heading`: same length (≤120 chars) and word-count
(≤12 words) caps as the existing numbered check, same trailing-punctuation
rejection (`.`, `,`, `;`), plus `text.isupper()` (Python's `str.isupper()`
correctly ignores digits/punctuation and only requires at least one cased
character be uppercase with none lowercase — `"5.2 SCOPE"` passes,
`"5.2 Scope"` doesn't).

### `backend/app/extraction.py` — DOCX font size

For each paragraph, resolve its effective font size by walking the
inheritance chain `python-docx` doesn't resolve automatically: first run's
explicit size, falling back to the paragraph's style's size, falling back
to "unresolvable" (`None`) if neither is set — in which case the font-size
signal simply doesn't fire for that paragraph (the other three signals
still apply; this is a silent, safe degradation, not an error).

**Baseline (revised during planning, based on empirical testing.)**
Originally planned as "the most common resolved size across all
paragraphs," but tested against a real fixture and found backwards: plain
`"Normal"`-styled body paragraphs typically resolve to `None` at *both*
the run and paragraph-style levels (Word's true default lives in
`styles.xml`'s `docDefaults`, which `python-docx` doesn't expose), while
headings usually do resolve (either an explicit run size, or the Heading
style itself defining one). A "most common resolved size" baseline would
therefore skew toward heading sizes, not body sizes — the opposite of
what a body baseline needs to be.

**Revised approach:** baseline = `document.styles["Normal"].font.size` if
that resolves, otherwise a hardcoded **11.0pt** fallback (Word's
overwhelmingly standard default when nothing else is set — an explicit,
documented assumption, not a guess dressed up as a fact). A paragraph's
font-size signal fires when its own resolved size (run-level or
style-level, as above) is not `None` and is at least 2pt larger than this
baseline, combined with the same short-line and no-trailing-punctuation
constraints used elsewhere. A paragraph whose own size is unresolvable
simply never triggers this signal — correct, since there's no size to
compare.

### `backend/app/extraction.py` — PDF font size (rebuilt around dict-mode)

**Revised during planning, based on empirical testing.** The original
approach (keep the plain-text pass untouched, correlate a second dict-mode
pass by paragraph order) was tested against a real fixture and found
broken: PyMuPDF's plain-text mode merges closely-spaced lines into a
single paragraph (joined by `\n`, not `\n\n`) in cases where dict-mode
correctly produces separate blocks — the two passes don't even produce the
same *count* of paragraphs to line up, let alone the same order. This is a
more general case of the exact problem Task 2 already patched around (the
conditional re-splitting logic for TOC-matched blocks that get merged with
adjacent body text in plain-text mode).

**Revised approach:** rebuild `_extract_pdf` to use `page.get_text("dict")`
as the sole source of truth for PDF paragraphs, replacing the current
plain-text-mode extraction (and the Task 2 conditional-splitting
workaround it required) entirely. Each dict-mode block with a `"lines"`
key (text blocks; image blocks lack this key and are skipped) becomes one
`Paragraph`: text is the concatenation of all span text within the block,
font size is the first span's `size` value (blocks are expected to be
typographically uniform — a heading block or a body block, not a mix),
and page number comes from the enclosing loop over `doc` (unchanged from
today).

This is a bigger change than originally scoped in the design (it replaces
tested, working extraction code, not just adds a signal alongside it), so
it needs its own careful verification: the existing PDF extraction tests
from Task 2 (including the TOC-matched-block-splitting test) must be
re-verified against the new dict-mode-based implementation before this is
considered complete, in addition to the new font-size-specific tests below.

Baseline computation and the 2pt-larger-than-baseline threshold work the
same way as DOCX, computed across all resolved sizes in the document.

## Testing

- New unit tests for `_looks_like_all_caps_heading` and the DOCX/PDF
  font-size resolution functions, each in isolation.
- New tests for the swallowing-bug fix: a paragraph list with one
  structurally-signaled heading and one plain-numbered heading elsewhere,
  asserting both are detected as section boundaries.
- New tests for font-size detection on constructed DOCX/PDF fixtures (a
  document with a normal-size body paragraph and a larger-font paragraph
  with no style/TOC/numbering), asserting the larger one is flagged and
  the body text is not (the specific false-positive `unstructured` showed
  us needs an explicit regression test here).
- Full backend suite re-run after the change to confirm no regression in
  the downstream stages that consume `Paragraph`/`Section` objects.
- Re-run of `test-documents/` fixtures (the TXT edge-case set) to confirm
  the ALL-CAPS addition and the swallowing-bug fix don't change behavior
  there in unintended ways, since `sectioning.py` is shared by all formats.

## Out of Scope

- `unstructured` library — rejected per the findings above.
- Bold-only detection (no size difference).
- Centered, colored, or font-family-only heading conventions.
- Multi-column PDF reading order.
- Any change to TXT extraction itself (TXT benefits from the ALL-CAPS and
  swallowing-bug fixes only because `sectioning.py` is shared, not from
  any TXT-specific work).
