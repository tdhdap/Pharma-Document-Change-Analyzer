# Section Added & Deleted Detection — Design

**Status:** Approved for implementation

## Purpose

Sourced directly from reviewer feedback: when a whole section is added or
removed between document versions, the comparison pipeline today only
reports it indirectly, through its individual body paragraphs.

- **Section added:** a section in `match_result.inserted_indices` (no match
  in the old document) has its body paragraphs dumped into the ordinary
  `added_paragraph` bucket (`pipeline.py:85-87`) — one row per paragraph,
  never a "new section" fact. The heading itself is never converted into a
  change at all, since only body paragraphs become rows. A new section
  that's heading-only (no body yet) produces **zero** rows and is invisible
  to a reviewer.
- **Section deleted:** exact mirror (`pipeline.py:82-84`) — a deleted
  section's body paragraphs become individual `deleted_paragraph` rows, the
  section itself is never reported as removed, and a heading-only deleted
  section produces zero rows.

(A third reviewer remark — "section moved" — is already resolved by the
`section_reordered` detector shipped earlier the same day; not part of this
spec.)

## Decision

Two new `Change.change_type` values, both risk `"High"` (a whole section
appearing or disappearing is a substantive structural change to a regulated
document — more significant than a single content edit inside a section):

- **`section_added`** — one `Change` per section in
  `match_result.inserted_indices`.
- **`section_deleted`** — one `Change` per section in
  `match_result.deleted_indices`.

Both **replace** the existing per-paragraph rows for that section's content
— a whole unmatched section is reported as one structural fact instead of N
scattered paragraph rows. This also directly fixes the heading-only-section
gap: the new signal fires from `match_result`'s section-level indices, not
from the presence of body paragraphs, so an empty/near-empty section still
produces a row.

**Excluded: synthetic headings from headingless documents.** `sectioning.py`
invents one section per paragraph, headed `"Paragraph 1"`, `"Paragraph 2"`,
etc., when a document has no real headings at all (the C2 test scenario —
"no headings at all, tests the no-structure fallback"). Those synthetic
sections can land in `inserted_indices`/`deleted_indices` exactly like real
sections. If `section_added`/`section_deleted` fired on them, an ordinary
paragraph addition in an unstructured document would get relabeled as a
High-risk "section added" instead of the existing Medium-risk
`added_paragraph` — a real behavior regression for headingless input, not a
genuine structural section event. `detect_section_reordering` already
solves this exact problem for its own signal with an `_is_synthetic_heading`
check; this spec reuses that logic (promoted to a shared, non-underscored
helper — see below) and pipeline.py keeps the existing per-paragraph
fallback for synthetic-headed indices specifically.

`old_text`/`new_text` contain the heading followed by every body paragraph,
newline-joined, on whichever side exists (empty string on the other side).
Nothing is lost by consolidating multiple paragraph rows into one — the
reviewer sees the same content, just in one place instead of scattered
across several unrelated-looking rows.

## Design per component

### `backend/app/section_structure.py`

Two new functions, alongside the existing `detect_section_renumbering`/
`detect_section_reordering`:

```python
def detect_section_added(
    inserted_indices: list[int],
    new_sections: list[Section],
) -> list[Change]: ...

def detect_section_deleted(
    deleted_indices: list[int],
    old_sections: list[Section],
) -> list[Change]: ...
```

Both functions first skip any index whose section has a synthetic heading
(reusing the promoted `is_synthetic_heading` helper, see below) — no
`Change` is produced for those, and the index is left for pipeline.py's
existing per-paragraph fallback to handle instead.

For every other (real-headed) index, build one `Change`:
- `section`: the section's own heading (only one side exists here, unlike
  renumbering/reordering which always have both an old and new heading).
- `old_text`/`new_text`: `""` on the side that doesn't exist; on the side
  that does, the heading followed by every paragraph in `Section.paragraphs`,
  each on its own line (`"\n".join([heading] + [p.text for p in
  section.paragraphs])`).
- `old_page`/`new_page`: the first body paragraph's `.page` if the section
  has body paragraphs, else `None` (a heading-only section has nothing to
  point a page number at — consistent with how renumbering/reordering
  already use `None` when there's no single paragraph to anchor to).
- `source`: `"Table"` if any paragraph in `section.paragraphs` has
  `from_table == True`, else `"Body"` — reuses the existing source
  convention (`pipeline.py` already computes this the same way for every
  other change type) rather than inventing a new rule.
- `confidence`: `1.0` (rule-based, not probabilistic).
- `reason`: `f"New section added: '{heading}'."` for `section_added`,
  `f"Section deleted: '{heading}'."` for `section_deleted`.
- `ai_risk_level`: via `risk_rules.assign_risk(change_type)`.

### `backend/app/risk_rules.py`

Add to `RISK_TABLE`:
```python
"section_added": "High",
"section_deleted": "High",
```

### `backend/app/pipeline.py`

In `compare_documents`, alongside the existing renumbering/reordering calls
(both already run right after `match_result = section_matching.match_sections(...)`):

```python
changes.extend(section_structure.detect_section_added(
    match_result.inserted_indices, new_sections
))
changes.extend(section_structure.detect_section_deleted(
    match_result.deleted_indices, old_sections
))
```

**Required change to the existing orphan-building loops:** the two loops
that currently dump a whole unmatched section's paragraphs into
`orphan_deletes`/`orphan_inserts` (`pipeline.py:82-87`) must become
conditional on the section's heading being synthetic:

```python
for idx in match_result.deleted_indices:
    sec = old_sections[idx]
    if section_structure.is_synthetic_heading(sec.heading):
        orphan_deletes += [(p, sec.heading) for p in sec.paragraphs]
for idx in match_result.inserted_indices:
    sec = new_sections[idx]
    if section_structure.is_synthetic_heading(sec.heading):
        orphan_inserts += [(p, sec.heading) for p in sec.paragraphs]
```

Real-headed unmatched sections are now handled exclusively by
`detect_section_added`/`detect_section_deleted`, so they must stop flowing
into the orphan lists — otherwise their paragraphs would *also* flow into
`move_reconciliation`, either double-reporting them as `added_paragraph`/
`deleted_paragraph` alongside the new `section_added`/`section_deleted`
row, or — worse — getting them falsely reconciled as `moved_paragraph` to
an unrelated section elsewhere in the document, if wording happens to be
similar. Synthetic-headed unmatched sections (headingless documents) keep
flowing into the orphan lists exactly as before, preserving today's
behavior for the no-structure fallback case.

### `backend/app/section_structure.py`: promote `_is_synthetic_heading`

Rename the existing private `_is_synthetic_heading` (and its backing
`_SYNTHETIC_HEADING_PATTERN`) to `is_synthetic_heading` — dropping the
leading underscore — since `pipeline.py` now needs to call it too, not just
`detect_section_reordering`. Behavior is unchanged; this is a rename only.
Update the one existing call site inside `detect_section_reordering`
accordingly.

**Explicitly unaffected by this removal:** the `for match in
match_result.matches` loop (`pipeline.py:59-80`), which handles partial
paragraph adds/deletes/replaces *within* an otherwise-matched section —
these are normal content edits, not whole-section events, and continue to
produce `added_paragraph`/`deleted_paragraph`/regular content-change rows
exactly as they do today.

### Unaffected

`detect_section_renumbering`/`detect_section_reordering` — unchanged, they
already only operate on `match_result.matches` (matched sections), which
this spec doesn't touch. `move_reconciliation.py` — unchanged; it still
correctly handles a paragraph relocating between two *matched* sections
(the orphans it receives are now exclusively genuine mid-section orphans,
never whole-section content). `sectioning.py`, `section_matching.py`,
`export.py`, frontend — no changes needed; both new `change_type` strings
flow through the existing generic `Change` → DB → export → Detailed
Changes table path unmodified, same as every other type.

## Testing

- A genuinely new section with several body paragraphs → one
  `section_added` row containing the heading + all paragraph text; no
  `added_paragraph` rows for that section's content.
- A new section that is heading-only (no body paragraphs) → still produces
  a `section_added` row (regression guard for the "may be missed" gap;
  `old_text`/`new_text`'s non-empty side is just the heading, `new_page` is
  `None`).
- Mirror of both cases for `section_deleted`.
- A section that is partially edited but still matched (a normal content
  change, not a whole-section event) → completely unaffected, still
  produces ordinary per-paragraph change rows as today — regression guard
  proving this feature doesn't touch matched-section handling.
- A deleted/added section whose paragraphs are table content
  (`from_table == True`) → `source == "Table"` on the resulting change.
- `risk_rules.assign_risk("section_added")` and
  `assign_risk("section_deleted")` both return `"High"`.
- A document with an unmatched deleted section and an unmatched added
  section whose wording happens to be similar → confirm they are NOT
  reconciled as a `moved_paragraph`/`moved_table_content` (regression guard
  for the `orphan_deletes`/`orphan_inserts` change).
- A headingless document (no real headings on either side — the C2
  scenario) with a paragraph added/deleted → still produces the existing
  `added_paragraph`/`deleted_paragraph` row via the orphan fallback, NOT a
  `section_added`/`section_deleted` row (regression guard for the
  synthetic-heading exclusion — this is the core correctness property of
  this plan, since without it every C2-style comparison would misreport
  ordinary paragraph edits as High-risk section events).
- Full backend suite re-run to confirm no regressions (this must include
  the existing C1/C2-style tests already in the suite, since this feature
  changes code paths those scenarios exercise).

## Out of Scope

- `section_renumbered`/`section_reordered` — already correct, apply only to
  matched sections; no change needed.
- Mid-section paragraph moves between two matched sections — already
  correct via `move_reconciliation.py`; no change needed.
- Any frontend UI change — both new types flow through the existing
  Detailed Changes table uniformly, same as every other `change_type`.
