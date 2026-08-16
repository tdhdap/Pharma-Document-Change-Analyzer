# DOCX Text Box Extraction — Design

**Status:** Approved for implementation

## Purpose

python-docx has **zero API** for Word text boxes — confirmed empirically
before writing this spec, not assumed. A paragraph containing a text box
reads as completely empty (`''`) through every normal python-docx reading
path (`Paragraph.text`, `Document.iter_inner_content()`), regardless of how
much real text sits inside the box. This is genuine, silent content loss:
a reviewer comparing two SOP versions would never see a change made inside
a text box (a common device for callout boxes, warning labels, or
letterhead branding elements in pharma documents).

## Decision

**Extraction only** (matching the established pattern for every DOCX
extraction feature in this series) — no new comparison logic, no
persistence/export changes, no frontend changes. Text box paragraphs flow
into the existing extraction pipeline exactly like header/footer content
does today: as their own pseudo-sections, processed by the same
downstream comparison machinery with zero special-casing.

**Unified extraction for both text box formats.** Word represents text
boxes two ways — modern DrawingML (`<w:drawing>` → `<wps:txbx>`) and legacy
VML (`<w:pict>` → `<v:textbox>`, used in compatibility mode / older
documents). Both wrap their actual paragraph content in a plain
`<w:txbxContent>` element — verified empirically by constructing real
examples of both and confirming the same `.//w:txbxContent` XPath-style
search finds each one identically, with no format-specific branching
needed anywhere in the extraction code.

**Scope: whole document** (body + every already-active header/footer
variant, per your choice) — reuses `_docx_header_footer_specs`'s existing
filtering (which variant of which section is actually non-inherited/
toggle-active) rather than re-deriving that logic, so a text box sitting
inside an inactive/inherited header variant is correctly never surfaced
(consistent with how that content is invisible to a reader too).

**Representation: simple sequential pseudo-sections**, `"Text Box 1"`,
`"Text Box 2"`, ... — one global counter across the whole document, no
location qualifier (per your choice; unlike headers/footers, a text box's
number is already a unique identifier on its own, no ambiguity to resolve
with a qualifier). Appended to the paragraph stream after headers/footers
(per your choice) — the simplest placement, requiring no change to the
core paragraph-walking loop's structure.

**`from_table`/`table_position` stay at their defaults** (`False`/`None`)
for all text box content, even when a text box happens to be anchored
inside a table cell — a floating text box isn't part of that table's grid
structure, and its own "Text Box N" heading already makes its origin
unambiguous without needing table-cell coordinates that wouldn't
meaningfully apply anyway.

**No collision with existing extraction.** Verified empirically:
`iter_inner_content()` (the walk every other extraction path already
uses) never descends into a `<w:drawing>`/`<w:pict>` element at all — a
host paragraph containing a text box is treated as an ordinary (if empty)
paragraph by that walk. The new text-box search and the existing
paragraph/table walk therefore operate on structurally disjoint data; no
double-extraction is possible.

**Nested text boxes** (a text box inside another text box — rare, but
possible in Word) are handled correctly for free by this design: verified
empirically that a recursive `.//w:txbxContent` search finds each nesting
level as its own independent match, an outer text box's own paragraph text
correctly excludes any nested drawing's content (python-docx's run-text
resolution only reads `<w:t>` elements within that specific run, ignoring
sibling `<w:drawing>` content), and each nested box's paragraphs are
reachable only via direct-child traversal of its own `<w:txbxContent>` —
no double-counting, no data corruption, no special-casing required.

## Design per component

### `backend/app/extraction.py`

**New helper**, finds every text box's paragraphs under a given XML root:

```python
def _iter_text_box_paragraphs(root_element, doc):
    for txbx in root_element.findall(".//" + qn("w:txbxContent")):
        for raw_p in txbx.findall(qn("w:p")):
            yield DocxParagraph(raw_p, doc)
```

(`DocxParagraph(raw_p, doc)` wraps a raw lxml `<w:p>` element into a real
python-docx `Paragraph` object, using the `Document` itself as the parent
for style resolution — verified empirically that `.text`, `.style`,
`.runs` all resolve correctly this way, identical to how a "normal"
python-docx paragraph object behaves.)

**In `_extract_docx`**, after the existing header/footer emission block:
collect text-box paragraph groups from `doc.element.body` (covers the
whole body including inside tables, since the search is transitive) and
from each active header/footer source already returned by
`_docx_header_footer_specs(doc)` (reusing that call rather than re-running
it, and reusing its already-correct source objects). For each `txbxContent`
group with any non-empty paragraph text, emit `"Text Box {n}"` (1-indexed,
sequential across the whole document) as a pseudo-heading, followed by its
paragraphs converted via the existing `_docx_paragraph_to_model` with
`allow_text_pattern_heading=False` (matching the same reasoning already
applied to tables/headers/footers — short captions and labels inside a
text box are exactly the kind of content that looks like a heading by
shape alone) and `from_table=False`, `table_position=None`.

### Unaffected

`_iter_docx_paragraphs`, `_docx_header_footer_specs`,
`_header_footer_heading_text`, `table_id_counter` threading — untouched;
this feature only adds a new, independent search over the same document,
not a modification to how the existing walk works. `sectioning.py`,
`section_matching.py`, `section_structure.py`, `pipeline.py`, `db.py`,
`repository.py`, `export.py`, frontend — no changes; `"Text Box N"`
pseudo-sections flow through the exact same generic `Section.heading`
path every other pseudo-section (`"Page Header"`, etc.) already does.

## Testing

- A text box (modern DrawingML format) with one paragraph of real text →
  produces a `"Text Box 1"` pseudo-section containing that text.
- A text box (legacy VML format) with real text → same result, proving
  the unified search handles both formats identically.
- A text box with multiple paragraphs → all paragraphs appear under the
  same `"Text Box N"` pseudo-section, in order.
- A paragraph with multiple runs inside a text box (e.g. mid-sentence
  formatting change) → text joins correctly into one coherent string.
- Multiple text boxes in one document → sequential `"Text Box 1"`,
  `"Text Box 2"`, ... in document order.
- An empty text box (no real text) → produces no pseudo-section at all
  (same whitespace-only-content guard already used for headers/footers).
- A text box anchored inside a table cell → its content is extracted with
  `from_table=False`, `table_position=None` (not treated as table-grid
  content), and the host cell's own regular text (if any) is extracted
  completely independently and unaffected.
- A text box inside an active first-page/even-page header or footer
  variant → extracted and included; inside an inactive/inherited variant
  → correctly not extracted (matches the existing header/footer
  toggle-gating behavior, since this reuses `_docx_header_footer_specs`
  directly).
- A text box nested inside another text box → both become independent
  `"Text Box N"` pseudo-sections with correctly separated content, no
  duplication.
- A document with no text boxes at all → zero regression, output
  identical to before this feature (this must hold for every existing
  test fixture already in this test suite).
- Full backend suite re-run to confirm no regressions.

## Out of Scope

- Any comparison/detection logic specific to text boxes — this is
  extraction only, same generic comparison pipeline as every other
  pseudo-section.
- Persisting, exporting, or surfacing anything text-box-specific beyond
  the heading text itself — no new `Change` fields, no frontend changes.
- PDF/TXT — neither format has an equivalent text-box concept.
- Any positional/anchor tracking (which paragraph a text box is anchored
  near) — out of scope per your "simple" choice; could be a future
  follow-up, mirroring how table coordinates got richer over two separate
  plans in this same series.
