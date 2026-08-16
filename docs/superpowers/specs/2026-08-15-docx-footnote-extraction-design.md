# DOCX Footnote Extraction — Design

**Status:** Approved for implementation

## Purpose

Word footnotes live in a completely separate OOXML part, `word/footnotes.xml`,
cross-referenced from the main document body via `<w:footnoteReference>`
elements — invisible to every existing extraction path (python-docx exposes
no API for this part at all; it loads as an opaque, unparsed `Part`). A
reviewer comparing two SOP versions today would never see a footnote
citation change, even though footnotes are a common way to cite reference
standards (e.g. "See ICH Q1A(R2) for stability testing requirements.") in
pharma documents — genuine, silent content loss, the same class of problem
text boxes had, just structurally different (an out-of-line OOXML part
instead of an inline element).

## Decision

**Extraction only** (matching the established pattern for every DOCX
extraction feature in this series) — no new comparison logic beyond what's
needed to prevent a predictable false positive (below), no persistence/
export/frontend changes. Footnote paragraphs flow into the existing
extraction pipeline exactly like text box content does today: as their own
pseudo-sections, processed by the same downstream comparison machinery with
zero special-casing.

**Discovery via relationship type, not content-type sniffing.** The
footnotes part is located through `doc.part.rels`, filtering for
`reltype == "http://schemas.openxmlformats.org/officeDocument/2006/relationships/footnotes"`
— verified empirically that python-docx exposes this relationship
correctly even though it has no registered `Part` subclass for the
footnotes content type (the part loads as a generic, opaque
`docx.opc.part.Part` with only a raw `.blob`, no parsed element). Verified
this relationship is cleanly absent — no error, no special-casing needed —
on documents with no footnotes at all, which is every one of the ~18 real
DOCX fixtures already in this test suite.

**Parsing via `docx.oxml.parse_xml`, not `lxml.etree.fromstring`.** Verified
empirically that `parse_xml(footnotes_part.blob)` alone produces fully
python-docx-classed elements (`.text`, `.runs`, table walking all resolve
correctly) with no further wiring — unlike text boxes, where inline
fragments built with plain `etree.fromstring` needed to be appended into a
live document tree before they classed correctly, footnotes.xml is parsed
as its own independent, complete OOXML part, so this concern doesn't apply
here.

**Filtering out Word-internal boilerplate footnotes.** Each `<w:footnote>`
carries a `w:id` and an optional `w:type`. Verified empirically (by
constructing a real footnotes part) that Word-generated documents include
two non-content footnotes used purely for print layout —
`w:type="separator"` and `w:type="continuationSeparator"` — which must be
excluded. Real, user-authored footnote content has no `w:type` attribute
(or, per the OOXML spec's allowance, an explicit `w:type="normal"`) — both
treated as real content.

**Ordering and naming: `"Footnote N"`, sequential in reference order.**
The body is walked (reusing the existing paragraph walk) looking for
`<w:footnoteReference w:id="...">` inside each paragraph's XML, in document
order — verified empirically via
`paragraph._p.findall(".//w:footnoteReference")` that this reliably finds
each reference and its `w:id`, which is the join key back to the
footnotes part. For each reference encountered, in document order, emit
`"Footnote {n}"` (1-indexed, sequential, one global counter across the
whole document) as a pseudo-section heading, followed by that footnote's
extracted content. Mirrors the already-approved `"Text Box N"` pattern
exactly, including the trade-off it already accepted: content is appended
at the end of the paragraph stream (after text boxes), not inlined next to
its citation point, favoring the same "no change to the core body-walking
loop" simplicity already chosen for text boxes over exact positional
fidelity.

**Nested content: tables inside footnotes.** Per the OOXML schema, a
footnote's body allows both paragraphs *and* tables (the same content model
already handled for headers/footers/text boxes). Extraction reuses the
same table-aware `_iter_docx_paragraphs` walk already built for text boxes,
so a table inside a footnote (e.g. a small reference-standard citation
table) is captured correctly from the start — this plan does not repeat
the nested-table content-loss bug the text-box plan's final review had to
catch and fix separately. `allow_text_pattern_heading=False`,
`from_table=False`, `table_position=None` for all footnote content,
matching the identical reasoning already applied to text boxes (short
citation fragments look like headings by shape alone; footnote content
isn't part of any table's own grid structure even when it contains one).

**Renumbering-safety, built in from the start.** Adding or removing an
earlier footnote reference shifts every later footnote's number — the
exact bug class the text-box plan's final whole-branch review found and
had to fix after the fact (`"Text Box 1"` → `"Text Box 2"` when an earlier
box was inserted, with no content of its own having changed).
`detect_section_heading_changed`'s existing exclusion list
(`_is_page_header_or_footer_heading`, `_is_text_box_heading`) gains a third
check, `_is_footnote_heading`, matching a `"Footnote \d+"` pattern — in
this same plan, not discovered later by a whole-branch review. As with the
existing two exclusions, this check is scoped to `detect_section_heading_changed`
only, never folded into the shared `is_synthetic_heading` (which also gates
`detect_section_added`/`_deleted`/`_reordered`, and must keep firing
correctly for a genuinely added/removed/reordered footnote).

## Design per component

### `backend/app/extraction.py`

**New helper**, locates the footnotes part (if any) and returns its parsed
root element, or `None`:

```python
_FOOTNOTES_RELTYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/footnotes"
_EXCLUDED_FOOTNOTE_TYPES = {"separator", "continuationSeparator"}


def _footnotes_root(doc):
    for rel in doc.part.rels.values():
        if rel.reltype == _FOOTNOTES_RELTYPE:
            return parse_xml(rel.target_part.blob)
    return None
```

**New helper**, maps each real footnote's `w:id` to its extracted
paragraph group:

```python
def _footnote_content_by_id(footnotes_root, doc):
    content_by_id = {}
    for footnote in footnotes_root.findall(qn("w:footnote")):
        if footnote.get(qn("w:type")) in _EXCLUDED_FOOTNOTE_TYPES:
            continue
        footnote_id = footnote.get(qn("w:id"))
        content_by_id[footnote_id] = [
            para for para, _, _, _ in _iter_docx_paragraphs(_txbx_content_iter(footnote, doc))
        ]
    return content_by_id
```

(`_txbx_content_iter`, added by the text-box plan, walks direct `w:p`/
`w:tbl` children of any container element and wraps them as real
python-docx objects — reused here unchanged, since a footnote's content
model is a direct-child walk over paragraphs and tables, identical in
shape to a text box's. No new content-walking helper is needed.)

**In `_extract_docx`**, after the existing text-box emission block: locate
the footnotes root via `_footnotes_root(doc)`; if present, build the
id→content map via `_footnote_content_by_id`; walk the body's paragraphs
(the same `paragraphs` list already built earlier in this function) in
order, and for each paragraph, find any `<w:footnoteReference>` elements
via `para_element.findall(".//" + qn("w:footnoteReference"))` (using the
raw element already available during the initial body walk — no second
document walk required). For each reference found, in document order,
look up its content by id; if present and non-empty, emit `"Footnote {n}"`
(sequential counter starting at 1) as a pseudo-heading followed by its
paragraphs, converted via the existing `_docx_paragraph_to_model` with
`allow_text_pattern_heading=False`, `from_table=False`,
`table_position=None` — appended after the text-box emission block, at the
end of the returned paragraph list.

A footnote `w:id` present in the body but absent from the footnotes part
(malformed document) is skipped silently — the same defensive posture
already used for a `w:txbxContent` group with no non-empty paragraphs.

### `backend/app/section_structure.py`

```python
_FOOTNOTE_PATTERN = re.compile(r"^Footnote \d+$")


def _is_footnote_heading(heading: str) -> bool:
    return bool(_FOOTNOTE_PATTERN.match(heading))
```

Added as a third check in `detect_section_heading_changed`, alongside the
existing `_is_page_header_or_footer_heading`/`_is_text_box_heading` checks.

### Unaffected

`_iter_docx_paragraphs`, `_docx_header_footer_specs`,
`_header_footer_heading_text`, `_iter_text_box_paragraphs`,
`_has_mc_fallback_ancestor`, `table_id_counter` threading — untouched.
`is_synthetic_heading`, `detect_section_added`, `detect_section_deleted`,
`detect_section_reordering`, `detect_section_renumbering` — untouched, and
verified (by the same reasoning already proven for text boxes and
headers/footers) to keep firing correctly for a genuinely added, deleted,
or reordered footnote, since none of them key off heading text shape the
way `detect_section_heading_changed` does. `sectioning.py`,
`section_matching.py`, `pipeline.py`, `db.py`, `repository.py`,
`export.py`, frontend — no changes; `"Footnote N"` pseudo-sections flow
through the exact same generic `Section.heading` path every other
pseudo-section already does.

## Testing

- A footnote referenced once from the body, with real text content →
  produces a `"Footnote 1"` pseudo-section containing that text.
- Multiple footnotes referenced in the body, in document order → sequential
  `"Footnote 1"`, `"Footnote 2"`, ... in reference order (not necessarily
  `w:id` order, which the OOXML spec does not guarantee matches reference
  order).
- A footnote whose body contains multiple paragraphs → all paragraphs
  appear under the same `"Footnote N"` pseudo-section, in order.
- A footnote whose body contains a table → the table's cell text is
  extracted (not silently dropped), with `from_table=False`,
  `table_position=None`.
- The two Word-internal boilerplate footnotes (`w:type="separator"`,
  `w:type="continuationSeparator"`) are never extracted as content, even
  when present.
- A document with no footnotes at all → zero regression, output identical
  to before this feature (must hold for every existing test fixture
  already in this suite).
- A document whose footnotes relationship is present but whose id lookup
  for a given body reference doesn't resolve (defensive case) → that
  reference is skipped without error, all other extraction proceeds
  normally.
- Pipeline regression test: adding an earlier footnote reference does not
  spuriously flag a later, unchanged footnote as `section_heading_changed`
  (mirrors the equivalent text-box and header/footer regression tests).
  A genuinely new footnote still fires `section_added`; a genuinely deleted
  one still fires `section_deleted`.
- Full backend suite re-run to confirm no regressions.

## Out of Scope

- Endnotes (`word/endnotes.xml`, `<w:endnoteReference>`) — a structurally
  parallel but entirely separate OOXML concept from footnotes, not
  requested, and rare in pharma SOP documents. A future follow-up could
  reuse most of this plan's approach if ever needed.
- Any comparison/detection logic specific to footnotes beyond the
  renumbering-safety guard — this is extraction only, same generic
  comparison pipeline as every other pseudo-section.
- Persisting, exporting, or surfacing anything footnote-specific beyond the
  heading text itself — no new `Change` fields, no frontend changes.
- Inline/positional placement of footnote content next to its citation
  point — out of scope per the placement decision above; a future
  follow-up, same as text boxes' equivalent trade-off.
- PDF/TXT — neither format has an equivalent footnote-part concept (PDF
  footnotes are just ordinary text near the bottom of a page, with no
  structural link back to their citation point; TXT has no footnote
  concept at all).
