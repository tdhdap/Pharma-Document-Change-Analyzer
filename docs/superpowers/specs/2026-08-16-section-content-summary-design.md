# Section Added/Deleted Content Summary — Design

**Status:** Approved for implementation

## Purpose

When a whole section is added or deleted, the report currently names the
section and nothing else about its size:

```
New section added: '5.0 Sampling'.
Section deleted: '7.0 References'.
```

A reviewer triaging a change list cannot tell whether an added section
carries three paragraphs of prose, a specification table, or nothing at
all — and those warrant very different amounts of attention. Appending a
short content summary lets that judgement happen without opening the
document.

## The counting problem

Verified empirically before writing this spec: a section holding one body
paragraph plus a single 4×3 table contains **13 paragraph objects** —
one real paragraph and twelve table cells, every cell a separate
`Paragraph` with `from_table=True` sharing one `table_position.table_id`.

A naive `len(section.paragraphs)` would therefore report "13 paragraphs"
for what a human reads as one paragraph and one table. That is worse than
showing no summary, because it is confidently wrong. Counting must
separate non-table paragraphs from distinct tables.

The invariant this relies on — that `from_table=True` always implies a
populated `table_position` — was checked across five real documents in
`test-documents/docx/` (AllFeaturesDemo, RequirementsCoverageDemo, C1,
SOP, TableHeaderFooterDemo): zero violations. PDF and TXT extraction never
set `from_table` at all, so they are unaffected.

## Decision

**Append the summary to the existing `reason` string.** `reason` is already
persisted to SQLite, already emitted in both JSON and CSV export, and
already rendered as a column on the Detailed Changes page. Putting the
summary there makes it appear everywhere at once with no database
migration, no export change, and no frontend change — the whole feature
lands in one file.

Resulting text:

```
New section added: '5.0 Sampling'. 3 paragraphs, 1 table.
New section added: '6.0 Limits'. 1 paragraph, 2 tables.
Section deleted: '7.0 References'. 2 paragraphs.
New section added: '9.0 Training Log'. No content.
```

**Granularity: paragraphs and distinct tables, not cells.** Cell counts
include header rows and read as inflated ("1 table (12 cells)" for a small
4×3 grid), and the paragraph-vs-table distinction is the one that actually
changes how a reviewer treats the section. A single collapsed total ("4
items") was rejected for losing exactly that distinction.

**A section with neither reads `"No content."`** rather than omitting the
summary. Silence is ambiguous — it could mean "empty" or "this feature
didn't run." An explicit statement is informative, and heading-only added
and deleted sections are a case this project already treats as
first-class: reporting them at all was a specific requirement, so
describing them precisely matters.

**Count `remaining_paragraphs`, not the section's raw contents.** Both
detectors already compute `remaining_paragraphs` by filtering out
`excluded_paragraph_ids` — content that merely relocated, which is
reported separately as its own move row and deliberately excluded from
this row's `old_text`/`new_text`. Counting the raw list would describe
content the row's own text does not contain, so the summary would
contradict the text displayed beside it. Counting the filtered list keeps
the two consistent.

## Design per component

### `backend/app/section_structure.py`

The only file that changes.

**Import change.** The helper's signature names `Paragraph`, which this
module does not currently import — it has only
`from app.models import Change, Section, SectionMatch`. Extend that line to:

```python
from app.models import Change, Paragraph, Section, SectionMatch
```

This is not optional pedantry. Verified on this project's Python (3.14):
PEP 649 defers annotation evaluation, so an undefined name in an
annotation raises nothing at import or call time — it fails only under
`typing.get_type_hints()`, and it raises `NameError` at import on Python
3.13 and earlier. Left unimported it would be a silent latent break.

**New private helper:**

```python
def _summarize_section_content(paragraphs: list[Paragraph]) -> str:
    body_count = sum(1 for p in paragraphs if not p.from_table)
    table_ids = {
        p.table_position.table_id
        for p in paragraphs
        if p.from_table and p.table_position is not None
    }
    parts = []
    if body_count:
        parts.append(f"{body_count} paragraph" + ("" if body_count == 1 else "s"))
    if table_ids:
        parts.append(f"{len(table_ids)} table" + ("" if len(table_ids) == 1 else "s"))
    if not parts:
        return "No content."
    return ", ".join(parts) + "."
```

Guarding on `p.table_position is not None` is defensive rather than
load-bearing: the invariant above holds in every real document checked,
but a table paragraph arriving without a coordinate should be skipped in
the table tally rather than raising `AttributeError` mid-comparison.

**In `detect_section_added`**, the reason changes from:

```python
reason=f"New section added: '{section.heading}'.", source=source,
```

to:

```python
reason=(
    f"New section added: '{section.heading}'. "
    f"{_summarize_section_content(remaining_paragraphs)}"
),
source=source,
```

**In `detect_section_deleted`**, the mirror change:

```python
reason=(
    f"Section deleted: '{section.heading}'. "
    f"{_summarize_section_content(remaining_paragraphs)}"
),
source=source,
```

Note the single space separating the two sentences, and that
`remaining_paragraphs` is already in scope at both call sites.

### Unaffected

`detect_section_heading_changed`, `detect_section_renumbering`, and
`detect_section_reordering` — these describe a heading or a position, not
a body of content, so a content count would be noise. `pipeline.py`,
`models.py`, `db.py`, `repository.py`, `export.py`, and the frontend — no
changes; `reason` is an existing string field flowing through paths that
already carry it.

## Testing

- A section with paragraphs only → `"N paragraphs."` with no table clause.
- A section with table content only → `"1 table."` with no paragraph clause.
- A section with both → `"N paragraphs, M tables."` in that order.
- A section containing two distinct tables → `"2 tables"`, driven by
  distinct `table_id` values rather than cell count.
- **A 4×3 table (12 cells) in a section reads as "1 table" and never as
  "12 paragraphs"** — the specific miscount this design exists to prevent.
- A heading-only section → `"No content."`, for both added and deleted.
- Singular/plural correctness at exactly 1 versus 2 for both nouns.
- A section whose content partly relocated elsewhere counts only
  `remaining_paragraphs`, matching what that row's `new_text`/`old_text`
  actually contains.
- The full reason string for both detectors, asserted end to end, so the
  separator and sentence order are covered rather than just the helper.
- Existing tests asserting on these two `reason` strings must be updated
  to the new text; the full backend suite re-run to confirm nothing else
  depended on the old wording.

## Out of Scope

- **A structured `content_summary` field on `Change`.** Considered and
  rejected for now: it would require a migration on the live `app.db`
  plus repository, export, and frontend changes, to serve programmatic
  consumers who do not currently exist. Revisit if a JSON consumer needs
  to filter or sort on these counts rather than read them.
- **Cell-level counts**, per the granularity decision above.
- **Summaries on any other change type**, per "Unaffected".
- **Changing what `excluded_paragraph_ids` filters**, or any other
  detection behavior. This spec only describes content already being
  reported; it does not alter which content is reported.
