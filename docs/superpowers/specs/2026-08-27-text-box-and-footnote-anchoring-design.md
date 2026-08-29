# Text Box and Footnote Anchoring — Design

**Status:** Approved for implementation

## Purpose

Text boxes and footnotes are extracted as pseudo-sections labelled only by
an ordinal — `Text Box 1`, `Footnote 2`. The label says nothing about where
in the document the item lives, so a reviewer who sees a change inside a
text box has no way to locate it short of opening the source document and
hunting.

This makes the label carry the item's location:

```
Footnote 1 (4.0 Procedure, paragraph 1)
Text Box 1 (8.0 Training Requirements, after paragraph 1)
Text Box 1 (9.0 Training Log, at start)
Text Box 2 (Page Header)
```

**Display only.** A changed anchor updates the label and reports nothing.
Detecting relocation as a change was considered and deliberately deferred —
it needs a new change type and a cascading-vs-deliberate distinction (a
section renumbered above an item shifts its anchor without the item moving),
which is the same problem the section-renumbering work solved and deserves
its own decision. The label work here is identical either way, so detection
can be layered on later without rework.

## What exists today, verified

Four facts were confirmed against the live code and the real test corpus
before writing this spec. Each one constrains the design.

**1. The anchor data is already in hand.** `_extract_docx` walks every body
paragraph and already harvests `w:footnoteReference` ids during that walk.
The anchoring paragraph is the loop variable at that moment; it is simply
discarded. Confirmed on `AllFeaturesDemo_v2`: footnote `1` is anchored to
*"Compression force shall be maintained at 18 kN ± 2…"*, under heading
`4.0 Procedure`. No second traversal is required for either feature.

**2. A text box's anchoring paragraph is usually empty.** Word parks a
floating shape in a paragraph of its own with no text. Verified on both
demo pairs — the anchor paragraph was empty in every case, while the
footnote's anchor paragraph carried real text. `_docx_paragraph_to_model`
drops empty paragraphs, so the anchor paragraph frequently never reaches
the output at all. **A paragraph-level anchor is therefore reliable for
footnotes and frequently meaningless for text boxes**, which is what forces
the wording rule in the next section rather than a single fixed phrasing.

**3. Embedding the anchor in the heading does not destabilise section
matching.** `match_sections` scores `heading + body` at a threshold of
`0.6`. Measured on the real text box and footnote sections: plain versus
anchored scored **0.919** and **0.894**, and anchored versus a *completely
different* anchor still scored **0.844** and **0.841**. A relocated item
matches its previous self with wide margin, so the anchor can live in the
identity string.

**4. No corpus document has a text box in a header or footer.** Surveyed
all DOCX pairs in `test-documents/docx/`: every text box is in the body.
`extraction.py` explicitly supports header/footer boxes — `text_box_roots`
is `[body] + [every header/footer source]` — and one unit test
(`test_extract_docx_text_box_inside_active_first_page_header_is_extracted`)
does build a synthetic document exercising it. So the path has unit
coverage but no realistic-document coverage, and the anchor design must
account for it because a header/footer box has no body paragraph to
anchor to.

## The label

### Format

`<Existing label> (<section>, <position>)`

The `N` counter is retained. Two text boxes can share one section, so the
ordinal remains what makes the label unique; the anchor is additive.

The section name is the heading text **as extraction emits it**, so it
matches the section the reviewer sees everywhere else. Items appearing
before the document's first heading anchor to `Preamble`, which is already
this codebase's name for that region and is already recognised by
`is_synthetic_heading`.

### The position rule

The ordinal counts **emitted body paragraphs within the current section**,
resetting at each heading, 1-based. Headings themselves are not counted.

One rule chooses the wording, keyed on whether the anchoring paragraph
survives extraction:

| Anchor paragraph | Wording | Meaning |
|---|---|---|
| Emitted | `paragraph N` | The item is *inside* paragraph N |
| Dropped as empty, N > 0 | `after paragraph N` | The item sits *between* paragraphs |
| Dropped as empty, N = 0 | `at start` | Nothing precedes it in the section |

This is one rule reading the data, not two special cases. A footnote whose
paragraph contains nothing but the reference marker gets `after paragraph
N` correctly, and a text box genuinely anchored inside a paragraph with
text gets `paragraph N` correctly — neither needs a branch of its own.

`at start` rather than `after paragraph 0`: verified necessary, since the
text box in `RequirementsCoverageDemo_v2` precedes every paragraph of its
section.

### Header and footer text boxes

A box inside a header or footer anchors to that header/footer's own
pseudo-heading, with **no ordinal**:

```
Text Box 2 (Page Header)
Text Box 3 (Page Footer (First Page))
```

"Paragraph 3 of the footer" is not a location anyone needs to navigate to.
The header/footer label already identifies the region precisely, including
its variant and — in multi-section documents — its section index.

## Design per component

### `backend/app/extraction.py`

`_extract_docx` gains anchor tracking inside the loop it already runs.

**Section state.** Two running values: the current heading text (initially
`"Preamble"`) and a count of emitted body paragraphs since that heading.
Both update from the *emitted model*, not the raw paragraph — a paragraph
`_docx_paragraph_to_model` drops must not advance the count.

**The heading test must be `sectioning._is_heading_paragraph(model)`, not
`model.is_heading`.** This is load-bearing and was verified before writing
it down. `model.is_heading` reflects only Word style and font size, while
section building additionally treats numbered and ALL-CAPS text as headings
via `allow_text_pattern_heading`. The two disagree constantly on the real
corpus — 10 documents contain headings `model.is_heading` misses entirely
(`RECORD RETENTION`, `1.0 Scope`, `2.0 Sample Preparation`, and 30+ more).
Tracking with `model.is_heading` would anchor items in those documents to
the wrong section, usually naming `Preamble` for the whole file. Using the
same predicate `split_into_sections` uses guarantees the anchor names the
section the reviewer actually sees. `extraction.py` already imports from
`sectioning`, so this adds no new dependency direction.

**A document with no real headings resolves correctly without special
handling** — verified. `split_into_sections` falls back to one section per
paragraph named `Paragraph N` only when it finds *no* headings, but the
pseudo-heading this feature anchors (`Text Box 1`) is itself emitted with
`is_heading=True`. Its presence guarantees the fallback never fires for a
document containing an anchored item, so leading content becomes a real
`Preamble` section and the label is accurate.

**Text box discovery moves into the body walk.** Each body paragraph is
searched for `w:txbxContent` descendants, alongside the `w:footnoteReference`
search already there, guarded by the existing `_has_mc_fallback_ancestor`
check — Word 2010+ wraps a user text box in `mc:AlternateContent` holding
both a DrawingML and a VML copy of identical content, so an unguarded
search finds every box twice.

Anchors are recorded in a dict **keyed by the `txbxContent` element object
itself**. Not by `id()`: lxml only guarantees a stable `id()` while a
Python reference to the proxy is alive, and this codebase has already been
bitten by exactly that — the merge-span pre-pass reported six elements
instead of five before it was keyed on the elements themselves.

**Emission order is unchanged.** The existing text-box pass still iterates
`text_box_roots` and still numbers boxes in `findall` order; it only gains a
dict lookup to resolve each box's anchor. A box found in a header/footer
root has no body anchor and falls back to the header/footer label. Keeping
this pass intact means the paragraph ordering of the extracted output, and
therefore every downstream section boundary, is untouched.

**One ordering change.** Footnote reference collection currently runs
*before* `_docx_paragraph_to_model` is called, so at that point it cannot be
known whether the paragraph will be emitted. Collection moves to after the
model call. The paragraph and its references are identical either way; the
move only makes the "inside it" versus "between them" test answerable.
`footnote_refs_in_order` accordingly carries the resolved anchor label
alongside each id.

### `backend/app/section_structure.py`

`_TEXT_BOX_PATTERN` and `_FOOTNOTE_PATTERN` widen to tolerate the suffix:

```python
_TEXT_BOX_PATTERN = re.compile(r"^Text Box \d+(\s\(.+\))?$")
_FOOTNOTE_PATTERN = re.compile(r"^Footnote \d+(\s\(.+\))?$")
```

**This is load-bearing and fails silently if missed.** Both patterns exist
to suppress `section_heading_changed` when a pseudo-heading's ordinal
shifts between versions. Anchored labels no longer match `^Text Box \d+$`,
so without this widening every anchored text box and footnote whose label
differs at all begins emitting a spurious heading-changed row.

The identical construction is already used by `_PAGE_HEADER_FOOTER_PATTERN`
(`^Page (Header|Footer)(\s\(.+\))?$`) for exactly this reason, so this
follows an established local precedent rather than inventing one.

Both widened patterns were verified against every label shape this design
produces, including the nested-parenthesis case a header/footer box creates
(`Text Box 3 (Page Footer (First Page))`, which matches — the greedy `.+`
consumes the inner parentheses correctly), and against the un-anchored
labels that must keep matching. `Text Box` and `My Text Box 1` correctly
do not match.

This widening is also what implements the display-only decision: an item
whose anchor changed keeps its content matched and reports nothing.

### Unaffected

`models.py`, `pipeline.py`, `table_diff.py`, `section_matching.py`,
`move_reconciliation.py`, `paragraph_diff.py`, `llm_classifier.py`,
`db.py`, `repository.py`, `export.py`, and the entire frontend. The label
is an ordinary heading string flowing through paths that already carry it,
and the Detailed Changes section filter populates dynamically. No schema
change and no migration: nothing new is persisted.

PDF and TXT extraction are untouched — neither extracts text boxes or
footnotes at all.

## Testing

- A footnote in the first paragraph of a section → `paragraph 1`.
- A footnote in a later paragraph → the correct ordinal, with headings not
  counted and the count reset at the section boundary.
- A text box between two paragraphs → `after paragraph N`.
- A text box preceding all content in its section → `at start`.
- A text box and a footnote before the document's first heading →
  `Preamble`.
- A footnote whose own paragraph holds nothing but the reference marker →
  `after paragraph N`, exercising the shared rule from the footnote side.
- A text box inside a header → the header's own label and no ordinal.
  `test_extract_docx_text_box_inside_active_first_page_header_is_extracted`
  already covers this shape; it needs its expected label updated to
  `Text Box 1 (Page Header (First Page))`. The nested parentheses are
  correct and were verified against the widened pattern.
- Two text boxes in one section → distinct labels, proving the counter
  still disambiguates once anchors are added.
- **A label whose anchor differs between versions produces no
  `section_heading_changed` row.** The regression guard for the pattern
  widening, and the assertion that enforces the display-only decision.
- Text boxes remain emitted in their existing order and position within the
  extracted paragraph list, so section boundaries are unchanged.
- Corpus sweep across every DOCX pair in `test-documents/docx/`: the only
  difference anywhere is the label text.

## Out of Scope

- **Detecting relocation as a change.** Deferred with its cascading-anchor
  problem, per the decision recorded above.
- Anchoring by page number. DOCX extraction does not compute page numbers;
  `Paragraph.page` is populated only on the PDF path.
- Ordinals for header/footer text boxes.
- Nested text boxes as a hierarchy. A box inside a box keeps whatever
  behaviour it has today; this changes labelling only.
- Any change to how text box or footnote *content* is compared, classified,
  or risk-rated.
