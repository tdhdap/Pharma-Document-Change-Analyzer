# DOCX Tables, Headers & Footers Extraction — Design

**Status:** Approved for implementation

## Purpose

`_extract_docx` currently only walks `doc.paragraphs` — python-docx's flat list
of body paragraphs. This silently misses:

1. **Tables** — `doc.tables` is a completely separate object tree; a table's
   cell content never appears in `doc.paragraphs` at all.
2. **Headers/footers** — `section.header`/`section.footer` are separate
   objects per document section, entirely outside the body's paragraph list.

This is proactive completeness work (no specific incident reported), closing
a gap before broader rollout: real-world pharma SOPs commonly use tables
(acceptance criteria, revision history) and running headers/footers
(document title, confidentiality notice, page numbering), none of which the
app currently sees or diffs.

**Explicitly out of scope for this pass** (a separate, harder sub-project):
footnotes and text boxes. Neither is exposed by python-docx's object model —
`Document` has no `.footnotes` attribute at all (footnote text lives in a
separate `word/footnotes.xml` part), and text box content lives nested
inside drawing/shape XML within a run, invisible to `Paragraph.text`. Both
require direct XML/lxml parsing with no library support, a meaningfully
different technical approach from this spec's python-docx-native one.

## Decision

### Tables: fold into the body's paragraph stream, in document order

Replace `_extract_docx`'s `for para in doc.paragraphs` with a walk over
`doc.iter_inner_content()` (python-docx 1.2.0, confirmed installed), which
yields paragraphs and tables interleaved in true document order. A new
recursive generator, `_iter_docx_paragraphs(content_iter)`, expands every
table it encounters into its cells' own paragraphs (each cell exposes the
same `iter_inner_content()`, so nested tables — a table inside a table
cell — are handled by recursing, not by a special case).

**Granularity: per cell**, not per row or per whole table. Each table cell
becomes its own paragraph-equivalent, going through the exact same
fine-grained diffing the app already does for body text — a single-cell
edit in a 20-row acceptance-criteria table reports as one precise change,
not the whole table flagged as different.

Because this yields real python-docx `Paragraph` objects — the same type
as body paragraphs — **all existing heading-detection logic (Word style,
font-size, ALL-CAPS, numbered) applies to table-cell text unchanged**. No
new detection code; the same per-paragraph checks just see more paragraphs.
A table positioned under "5.0 Acceptance Criteria" becomes part of that
section automatically, because it's now just paragraphs at that position in
the stream — `sectioning.py`, `section_matching.py`, and `pipeline.py` need
zero changes.

### Headers/footers: pseudo-sections, appended to the section list

Headers/footers have no position in reading order (they repeat per page),
so they can't be folded into the body stream the way tables are. Instead:
walk every `doc.sections`, skip any section's header/footer where
`is_linked_to_previous` is `True` (the common default — means "no content
of its own, inherits from before"), and collect paragraphs from the rest
via the same recursive `_iter_docx_paragraphs` walk (headers/footers can
themselves contain tables). If any header paragraphs are found across the
whole document, append a synthetic `Paragraph(text="Page Header",
is_heading=True)` to the end of the returned paragraph list, immediately
followed by the collected header paragraphs — together forming a "Page
Header" section once `split_into_sections` runs. Do the same for footers,
producing "Page Footer" appended after that. If a document has no header
(or no footer) content at all, no pseudo-section is emitted — no noise
from empty sections.

**Simplifying assumption:** if a document has multiple Word sections with
genuinely different (non-linked) headers, all their paragraphs are combined
into one "Page Header" section rather than split into "Page Header 1" /
"Page Header 2". Real pharma SOPs are near-universally single-section
documents; this avoids a numbering scheme for a rare case. Same for
footers.

**Explicitly out of scope:** `first_page_header`/`even_page_header`
variants (different content for a section's first page, or alternating
odd/even pages) — real python-docx features, but not something regulated
pharma SOPs realistically use. Only the primary `header`/`footer` is read.

## Design per component

### `backend/app/extraction.py`

- `_iter_docx_paragraphs(content_iter) -> Iterator[docx.text.paragraph.Paragraph]`
  — new. Yields paragraphs directly; for each table encountered, recurses
  into every cell's own `iter_inner_content()`.
- `_docx_paragraph_to_model(para, index, baseline_pt) -> Paragraph` — new,
  extracted from `_extract_docx`'s current inline body (lines 113-130
  today: strip/skip-empty, Word-style check, font-size check via
  `_docx_paragraph_font_size_pt`, shape guard via `_looks_like_heading_shape`,
  `is_heading = is_heading_style or is_heading_size`). Pure refactor — the
  detection logic itself does not change; it now just needs to run over
  three streams (body+tables, header, footer) instead of one.
- `_extract_docx` rewritten to: build the body stream via
  `_iter_docx_paragraphs(doc.iter_inner_content())`; build header/footer
  paragraph lists per the walk above; convert all three via
  `_docx_paragraph_to_model`; return body paragraphs followed by the
  "Page Header" pseudo-section (if any) followed by the "Page Footer"
  pseudo-section (if any).

### Unaffected

`backend/app/models.py`, `sectioning.py`, `section_matching.py`,
`paragraph_diff.py`, `move_reconciliation.py`, `pipeline.py`,
`regex_detectors.py`, `llm_classifier.py`, `risk_rules.py`, `export.py`,
and the frontend all need no changes — the two pseudo-sections and the
folded-in table cells flow through the existing pipeline exactly like any
other section/paragraph.

## Testing

- A DOCX with a simple table under a heading: assert each cell becomes its
  own paragraph, positioned in the section that heading creates.
- A DOCX with a table containing a nested table (table-in-cell): assert
  the nested table's cells are also extracted (recursion works).
- A DOCX with a Word-styled heading inside a table cell: assert
  `is_heading=True` fires the same as it would for a body paragraph (proves
  heading-detection is genuinely shared, not duplicated).
- A DOCX with a font-size-only heading inside a table cell: same proof for
  the font-size signal.
- A DOCX with header content set (non-linked) and a body with no
  header/footer: assert a "Page Header" section appears with the right
  paragraphs, and no "Page Footer" section appears at all.
- A DOCX with both header and footer set: assert both pseudo-sections
  appear, in the right order, each with correct content.
- A DOCX with a header explicitly linked to previous (or never set):
  assert no "Page Header" section is created — no false-positive empty
  section.
- A DOCX with no tables, no headers, no footers: assert output is
  byte-identical to today's behavior (regression guard — this refactor
  must not change existing extraction for documents that don't use any of
  these features).
- Full backend suite re-run to confirm no regressions in downstream stages
  that consume `Paragraph`/`Section` objects.

## Out of Scope

- Footnotes and text boxes — a separate sub-project requiring raw XML/lxml
  parsing (python-docx exposes neither).
- `first_page_header`/`even_page_header` variants.
- Per-Word-section distinct header/footer numbering (multiple distinct
  headers collapse into one combined "Page Header" section, per the
  simplifying assumption above).
- Comments, endnotes, content controls/structured document tags, embedded
  objects — not requested, not addressed here.
- Any change to PDF or TXT extraction.
