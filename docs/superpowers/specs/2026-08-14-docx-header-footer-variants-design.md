# DOCX First-Page/Even-Page Headers & Footers — Design

**Status:** Approved for implementation

## Purpose

Today's DOCX extraction only reads each section's **default** header/footer
(`section.header`/`section.footer`), and merges every section's content into
one generic "Page Header" pseudo-section and one generic "Page Footer"
pseudo-section — with no way to tell which section a given header/footer
paragraph came from. This misses two real Word features entirely:

- **First-page headers/footers** — a section can have distinct content on
  its first page (`section.first_page_header`/`first_page_footer`), gated by
  `section.different_first_page_header_footer`.
- **Even-page headers/footers** — a document can have distinct content on
  even-numbered pages (`section.even_page_header`/`even_page_footer`),
  gated document-wide by `doc.settings.odd_and_even_pages_header_footer`.

Both gates were verified empirically against python-docx before writing
this spec: setting text on `first_page_header`/`even_page_header` does
**not** make Word display it — the corresponding toggle must also be on.
Confirmed concretely: a document with text in both variants but both
toggles left off round-trips that text in the file's XML while never
displaying it to a reader.

## Decision

**Toggle-gated extraction:** first-page content is only extracted when
`section.different_first_page_header_footer` is `True`; even-page content
is only extracted when `doc.settings.odd_and_even_pages_header_footer` is
`True`. Content sitting inactive in the XML (toggle off) is not extracted —
this tool reports what a reader actually sees, not what's merely present in
the file. If a document's toggle is later flipped on, that itself is a real
change (previously-invisible content becoming visible) that should
legitimately show up as new content appearing — not something this
decision hides.

**Split into distinct pseudo-sections**, not just tagged with invisible
metadata (unlike the table-coordinates work, which was deliberately
extraction/storage-only) — this is a real, visible change to the Detailed
Changes report, so each section's header/footer content becomes its own
pseudo-section instead of being merged into one shared bucket.

**Naming scheme**, designed to keep every currently-passing single-section
document's behavior byte-for-byte unchanged:

| Case | Heading text |
|---|---|
| Default variant, document has exactly 1 section | `"Page Header"` / `"Page Footer"` (unqualified — today's exact behavior) |
| Default variant, document has 2+ sections | `"Page Header (Section 2)"` (1-indexed; every section qualified once there's more than one, not just section 1) |
| First-page variant, 1 section | `"Page Header (First Page)"` |
| First-page variant, 2+ sections | `"Page Header (Section 2, First Page)"` |
| Even-page variant, 1 section | `"Page Header (Even Page)"` |
| Even-page variant, 2+ sections | `"Page Header (Section 2, Even Page)"` |

(Footer follows the identical pattern with `"Page Footer"`.)

**Ordering** unchanged at the macro level: every header pseudo-section
first (in section order, then default → first-page → even-page within each
section), then every footer pseudo-section, same as today's "all headers,
then all footers" — just more granular within each half.

**One existing test becomes stale, not broken:**
`test_extract_docx_multiple_sections_with_distinct_headers_combine`
currently only asserts both sections' header *text* appears somewhere,
without checking they're distinguished — its assertions will still
technically pass under this change, but its name ("combine") and intent
directly contradict the new behavior (the two headers no longer combine
into one bucket, they become two distinct pseudo-sections). This spec
requires renaming it and adding assertions that prove the two headings are
now distinct, rather than leaving a misleadingly-named regression guard in
the suite.

## Design per component

### `backend/app/extraction.py`

**`_docx_header_footer_specs(doc) -> list[tuple[str, int, str, ...]]`** (new
function) — walks `doc.sections`, and for each section builds the list of
active variants:
- always `("header", "footer", "")` (the default variant);
- plus `("first_page_header", "first_page_footer", "First Page")` only if
  `section.different_first_page_header_footer` is `True`;
- plus `("even_page_header", "even_page_footer", "Even Page")` only if
  `doc.settings.odd_and_even_pages_header_footer` is `True` (checked once
  for the whole document, not per-section — it's a document-level setting).

For each variant, `header_source = getattr(section, header_attr)` and
`footer_source = getattr(section, footer_attr)` are checked independently
via `is_linked_to_previous` — a section's header and footer for the same
variant can differ in whether they're linked, so both must be checked
separately, exactly as the existing code already does for the default
pair. Only variants with their own (non-linked) content produce a spec:
`(kind, section_index, variant_label, source)` where `kind` is `"header"`
or `"footer"`.

Returns every header spec first (built while walking sections in order,
variant order default→first-page→even-page within each section), followed
by every footer spec in the same order — implemented as two internal lists
concatenated at the end, so the macro-ordering is structural, not
incidental.

**`_header_footer_heading_text(kind, section_index, variant_label, multi_section) -> str`**
(new function) — pure function implementing the naming table above:

```python
def _header_footer_heading_text(kind, section_index, variant_label, multi_section):
    base = "Page Header" if kind == "header" else "Page Footer"
    parts = []
    if multi_section:
        parts.append(f"Section {section_index + 1}")
    if variant_label:
        parts.append(variant_label)
    if not parts:
        return base
    return f"{base} ({', '.join(parts)})"
```

**`_extract_docx`'s header/footer block** (currently the two combined
`header_paragraphs`/`footer_paragraphs` lists and their two emission
blocks) is replaced by one loop over `_docx_header_footer_specs(doc)`:
extract each spec's paragraphs via the existing `_iter_docx_paragraphs`
(same `table_id_counter` threaded through, unchanged from the
table-coordinates work), filter out whitespace-only/empty ones (same guard
as today, moved to operate per-spec instead of on the two combined lists),
skip the spec entirely if nothing real remains, otherwise emit
`_header_footer_heading_text(...)` as a pseudo-heading `Paragraph` followed
by the spec's real paragraphs — same `_docx_paragraph_to_model` call
pattern as today, just per-spec instead of per-combined-list.

### Unaffected

`_iter_docx_paragraphs`, `_docx_paragraph_to_model`, the `table_id_counter`
threading, `TableCoordinate`/`table_position` — untouched; this feature
only changes *which* header/footer sources get walked and *what heading
text* wraps their output, not how paragraphs within them are processed.
`sectioning.py`, `section_matching.py`, `section_structure.py`,
`pipeline.py`, `db.py`, `repository.py`, `export.py`, frontend — no
changes; the new pseudo-heading strings are just more `Section.heading`
values, flowing through the exact same generic paths every other section
heading already does.

## Testing

- Single section, default header/footer only, no variants active → heading
  text is exactly `"Page Header"`/`"Page Footer"`, unchanged from today —
  covers every currently-passing single-section test as a regression
  guard.
- Two sections, both with distinct default headers → `"Page Header (Section 1)"`
  and `"Page Header (Section 2)"` both appear as distinct headings, each
  containing only its own section's text — replaces
  `test_extract_docx_multiple_sections_with_distinct_headers_combine`
  (renamed, with real distinctness assertions added).
- First-page header/footer with the section's toggle ON → extracted,
  heading text includes `"First Page"`.
- First-page header/footer with content present but the toggle OFF → NOT
  extracted at all (the core correctness property of the toggle-gating
  decision).
- Even-page header/footer with the document-level toggle ON → extracted,
  heading text includes `"Even Page"`.
- Even-page header/footer with content present but the toggle OFF → NOT
  extracted.
- A section whose first-page variant is `is_linked_to_previous` even though
  the section's toggle is on → correctly not re-extracted as its own
  pseudo-section for that section (inherits from wherever it's linked to,
  matching the existing default-header inheritance behavior).
- First-page variant combined with a multi-section document → heading text
  is `"Page Header (Section 2, First Page)"` (both qualifiers present).
- A table inside a first-page header (once the toggle is on) → still
  correctly gets `from_table=True` and a `table_position`, proving this
  feature composes cleanly with the table-coordinates work already on this
  branch.
- Full backend suite re-run to confirm no regressions.

## Out of Scope

- Any comparison/detection logic that reasons about header/footer variants
  specifically (e.g. "first-page header changed") — this is extraction
  only, same `Change`-detection pipeline as every other section heading
  handles it generically.
- PDF/TXT — neither format has an equivalent header/footer-variant concept.
- Persisting, exporting, or surfacing anything variant-specific beyond the
  heading text itself — no new `Change` fields, no frontend changes.
