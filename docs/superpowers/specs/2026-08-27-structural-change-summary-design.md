# Structural Change Summary — Design

**Status:** Approved for implementation

## Purpose

The Change Summary page answers "how risky is this revision" and nothing
else. A reviewer opening a comparison sees five risk counts and has no idea
whether the document was restructured — whether sections were added,
removed, renamed, renumbered, or relocated — without scrolling the full
detail table and tallying by hand.

This adds a second metric row stating exactly that.

Structural change is a meaningful share of the report, not a footnote:
`AllFeaturesDemo` produces 12 changes of which **6 are structural**.

## What exists today, verified

Five facts were confirmed against the live code before writing this spec.

**1. The summary is derived, not stored.** `build_summary(changes)` is
called in `pipeline.py:212` for a fresh comparison and again in
`repository.py:83` when reloading from SQLite. The `comparisons` table has
columns for ids and a timestamp only. **No schema change and no migration
are required** — new fields recompute identically on reload.

**2. Nothing pins the summary's shape.** No test anywhere constructs
`ComparisonSummary` directly, and every assertion is per-field
(`summary.high_risk == 2`, `result["summary"]["total_changes"] == 1`).
Adding fields breaks no existing test.

**3. The export lists summary keys explicitly.** `export.py:22-27` names
each key, so new fields do **not** flow to the JSON export automatically —
they must be added there. The CSV export is per-change and is unaffected.

**4. `st.metric` accepts `help`.** Confirmed on the installed Streamlit
1.60.0. Tooltips are available without any extra dependency.

**5. `section_renumbered_cascade` appears nowhere in the corpus.** Measured
across all eleven DOCX pairs: `section_renumbered` occurs, its cascade
variant never does. This is a pre-existing coverage gap from the cascade
work, and this feature makes it visible — a permanently-zero metric reads
as a broken feature rather than a true zero.

Measured structural counts across the corpus:

```
AllFeaturesDemo            added 2  deleted 1  renamed 1  renumbered 1  moved 1
C1                         added 2  deleted 1  renamed 1  renumbered 1  moved 2
RequirementsCoverageDemo   added 1  deleted 1  renamed 1  renumbered 1  moved 1
SectionAddedDeletedDemo    added 3  deleted 1
SectionReorderRenumberDemo                      renumbered 3  moved 1
SOP                        added 2  deleted 1
A, B, C2, TableHeaderFooterDemo, TableHeaderVariantDemo   (none)
```

Five of eleven pairs have no structural changes at all.

## Decision

### The metrics

Six counts, rendered as a second `st.metric` row on the Change Summary
page, directly beneath the existing risk strip:

| Label | Change type | Tooltip |
|---|---|---|
| Sections Added | `section_added` | A section present in the new document only. |
| Sections Deleted | `section_deleted` | A section present in the old document only. |
| Sections Renamed | `section_heading_changed` | Heading wording changed. |
| Sections Renumbered | `section_renumbered` | Section number changed deliberately. |
| Sections Cascaded | `section_renumbered_cascade` | Number shifted only because a section above was added or removed; wording unchanged. |
| Sections Moved | `section_reordered` | Section changed position in the document. |

**Every label is prefixed "Sections".** The report below also contains
moved paragraphs, moved table content, and added and deleted table rows. A
bare "Moved: 1" would be read against any of those. The prefix is what
makes the strip unambiguous.

**The tooltip on Sections Cascaded is required, not decorative.** "Cascaded"
is not self-explanatory, and it is the one metric whose meaning a reviewer
cannot infer.

### Counting rules

**Sections Moved counts `section_reordered` only** — whole sections that
changed position. It deliberately excludes `moved_paragraph` and
`moved_table_content`, which are content moving *between* sections. `SOP`
is the case that settles this: it has one `moved_paragraph` and zero
`section_reordered`, so including content moves would report "Sections
Moved: 1" for a document in which no section moved. Content moves remain
visible as their own rows in the detail table.

**Renumbering is split into two counts, not merged.** "3 sections
renumbered" is alarming; "1 renumbered, 2 pushed along by an insertion
above" is routine. Merging them discards precisely the distinction the
cascade work was built to provide.

`section_renumbered_cascade` is a distinct change type, so matching must be
by equality. A prefix match such as `startswith("section_renumbered")`
would silently count every cascade twice — once in each metric. This is the
single most likely implementation error and gets its own test.

### The zero case

**All six metrics render always, including when every count is zero.** The
page keeps one consistent layout, and a reviewer can see that the check ran
and found nothing rather than wondering whether the block failed to load.
This applies to five of the eleven corpus pairs.

### Placement

The risk strip stays first; the structural row sits beneath it under a
`Structural Changes` subheader. Risk is what a reviewer triages on, so it
keeps the top position; both are above the fold.

## Design per component

### `backend/app/models.py`

`ComparisonSummary` gains six `int` fields. `build_summary` derives each by
counting `change_type` equality over the changes list, in the same pass
style the risk counts already use.

Fields default to `0` so any construction site that predates them keeps
working, consistent with how `TableCoordinate` gained its span fields.

### `backend/app/export.py`

Six keys added to the explicitly-listed `"summary"` dict, so the JSON
export carries the structural counts. Valuable in a regulated report, where
the exported artifact is the record. The CSV writer is per-change and needs
no change.

### `frontend/pages/1_Change_Summary.py`

A `Structural Changes` subheader and a second `st.columns(6)` row of
`st.metric` calls, each with its `help` tooltip. The page reads
`comparison["summary"]`, which already carries whatever the backend put
there.

### Unaffected

`db.py` (no schema change), `repository.py` (already calls `build_summary`),
`pipeline.py` (already calls it), `section_structure.py`, `table_diff.py`,
`extraction.py`, and the Detailed Changes and Review pages.

## Testing

- Each of the six counts derived correctly from a mixed change list.
- **A cascade change increments Sections Cascaded and leaves Sections
  Renumbered at zero.** The regression guard for the prefix-match error.
- All six are zero for a comparison with no structural changes, and the
  block still renders.
- Content moves (`moved_paragraph`, `moved_table_content`) do **not**
  increment Sections Moved — asserted against a change list containing both
  a content move and no section move, mirroring the real `SOP` pair.
- The six keys are present in the JSON export.
- The Change Summary page renders without exception, both with structural
  changes and with none.
- Corpus check: the counts for each DOCX pair match the change types
  actually present in that comparison's detail rows.

## Out of Scope

- Structural counts for tables (rows and columns added, deleted, moved) and
  for text boxes and footnotes. The same idea extends there, but the user's
  request is section-scoped and a twelve-metric strip would defeat the
  purpose.
- Making the metrics clickable filters into the Detailed Changes page.
- Persisting the summary. It is derived, and deriving it is correct.
- Building a DOCX fixture that exercises `section_renumbered_cascade`. The
  gap is noted above and remains open; it belongs to the cascade work, not
  to this display feature.
- Reconciling `build_summary` counting `ai_risk_level` while the Detailed
  Changes page counts reviewer overrides. A known, separate inconsistency.
