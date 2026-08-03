# DOCX Table/Header/Footer Heading False-Positive Fix — Design

**Status:** Approved for implementation

## Purpose

Manual testing of the DOCX tables/headers/footers extraction feature
(shipped earlier this session) surfaced a real false-positive: short
ALL-CAPS or numbered-looking values common in table cells and running
headers/footers get misdetected as their own headings by `sectioning.py`'s
text-pattern fallback, fragmenting content into spurious one-paragraph
sections instead of staying grouped where it belongs.

Concretely: `_looks_like_all_caps_heading` was designed and tuned for
body-text headings ("SCOPE", "MATERIALS AND METHODS") — short, uppercase,
no trailing punctuation. That same shape description is structurally
identical to common pharma table values ("HPLC", "NMT 0.5%", "USP <61>")
and header/footer boilerplate ("CONFIDENTIAL", "SOP-1234"). There is no way
to distinguish a real heading from these by shape alone — the rule was
never wrong on the body text it was built for, it's just being applied to
content it was never designed to see.

Verified directly against a real test document: a table with cells
"HPLC", "NMT 0.5%", "NMT 1.0%" under a "2.0 Acceptance Criteria" heading
had each of those cells become its own section instead of staying as body
content under the real heading — and separately, header text
"Confidential - SOP-1234" became its own section instead of staying nested
under the "Page Header" pseudo-section.

## Decision

Add `allow_text_pattern_heading: bool = True` to `Paragraph`. Default
`True` preserves today's behavior for every paragraph not touched by this
fix — all TXT/PDF paragraphs, all DOCX body paragraphs. DOCX extraction
sets it to `False` specifically for:

- table-cell paragraphs (wherever the table sits — body, header, or
  footer)
- header/footer paragraphs directly (not inside a table)

`sectioning.py`'s `_is_heading_paragraph` gains one check between the
existing structural signal and the text-pattern checks:

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

Structural signals (Word style, font-size — resolved during extraction
into `Paragraph.is_heading`) still work everywhere, unchanged: a genuinely
Word-styled or oversized-font heading inside a table cell or header is
still detected correctly, since that check runs first and doesn't consult
`allow_text_pattern_heading` at all. Only the ALL-CAPS/numbered-pattern
*guesswork* — reliable for narrative body text, unreliable for
abbreviation-heavy table data and short header/footer boilerplate — gets
turned off for the content where it misfires.

**Scope:** DOCX-only. PDF's extraction has no equivalent structural concept
of "this text came from a table cell" (PyMuPDF's dict-mode blocks don't
distinguish table cells from regular text blocks), so `_extract_pdf` and
`_extract_txt` are untouched — every paragraph they produce keeps the
default `allow_text_pattern_heading=True`.

## Design per component

### `backend/app/models.py`

`Paragraph` gains `allow_text_pattern_heading: bool = True`, alongside the
existing fields. Additive only — no existing field changes.

### `backend/app/sectioning.py`

`_is_heading_paragraph` gains the one new check shown above. No other
function in this file changes.

### `backend/app/extraction.py`

`_iter_docx_paragraphs` already recurses through tables; it now threads an
`allow_text_pattern_heading` parameter through the walk instead of
yielding bare `DocxParagraph` objects — it yields `(para,
allow_text_pattern_heading)` tuples. Defaults to `True` at the top level;
the table branch always recurses with `allow_text_pattern_heading=False`,
regardless of what value it was called with (once inside any table, the
flag can only go to `False`, never back to `True`).

`_docx_paragraph_to_model` gains a matching `allow_text_pattern_heading:
bool = True` parameter, threaded straight into the constructed
`Paragraph`. Its own heading-detection logic (Word style check, font-size
check) is completely unchanged.

`_extract_docx`'s three call sites update to unpack the new tuple shape
and pass the flag through:
- Body: `_iter_docx_paragraphs(doc.iter_inner_content())` — default
  `True` for top-level body paragraphs, `False` once recursed into any
  table.
- Header: `_iter_docx_paragraphs(section.header.iter_inner_content(),
  allow_text_pattern_heading=False)` — every header paragraph, whether
  direct or inside a nested table, gets `False`.
- Footer: identical, `allow_text_pattern_heading=False`.

## Testing

- A table-cell paragraph whose text is a short ALL-CAPS value ("HPLC")
  with no structural heading signal: assert it does NOT become its own
  section — it stays as body content under the preceding real heading.
- The same, for a numbered-looking table value (e.g. a cell reading
  "1.0" alone, unlikely but possible): assert no false heading.
- A table-cell paragraph that IS genuinely Word-styled or font-size
  heading (reusing the existing tests from the tables/headers/footers
  plan): assert it STILL correctly becomes a heading — proves the
  structural-signal path is untouched.
- A header/footer paragraph whose text is short ALL-CAPS ("CONFIDENTIAL",
  "SOP-1234"): assert it stays as body content under "Page Header"/"Page
  Footer" rather than becoming its own section.
- A body paragraph (not from a table, not header/footer) whose text is
  ALL-CAPS: assert it STILL becomes a heading — proves body-paragraph
  behavior is completely unaffected (the regression guard for this whole
  fix).
- Full backend suite re-run to confirm no regressions in TXT/PDF
  extraction or any downstream stage.
- Re-run the real `TableHeaderFooterDemo_v1.docx`/`_v2.docx` comparison
  (already built and used to discover this issue) and confirm the table
  cell values and header text no longer appear as their own sections in
  the result.

## Out of Scope

- PDF table/header/footer handling — no structural equivalent exists in
  the current PDF extraction approach.
- Any change to the ALL-CAPS/numbered-pattern rules themselves — they
  remain exactly as tuned for body text; this fix only changes which
  paragraphs are allowed to be tested against them.
