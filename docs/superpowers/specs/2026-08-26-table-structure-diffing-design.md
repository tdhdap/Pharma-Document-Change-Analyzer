# Table Structure Diffing — Design

**Status:** Approved for implementation

## Purpose

The tool has no notion of table structure. Cells are compared as loose
paragraphs inside a section, so a structural edit is reported as N
unrelated cell changes with nothing tying them together.

Verified on the existing `AllFeaturesDemo` pair: adding one row to a
three-column table produced three independent changes —

```
added_table_content  'Hardness'
added_table_content  '8 kg'
added_table_content  '7.9 kg'
```

— with no indication that they constitute a single row. Removing a row,
adding or removing a column, relocating either, or merging cells are all
invisible as structural facts today.

This adds four capabilities: **rows** added/deleted/moved, **columns**
added/deleted/moved, and **merged-cell** changes.

## What exists today, verified

Three facts were confirmed against the live code before writing this spec,
and each constrains the design:

**1. `table_id` is not stable across versions.** It is a global sequential
counter assigned during extraction. Inserting any table earlier in the
document shifts every later table's id — the same Assay/Water table was
`table_id=0` in one version and `table_id=1` in another that differed only
by an unrelated table added above it. **The diff must therefore match
tables between versions by content and must never key them by id.**

**2. Merge spans exist in the source but are discarded.** The OOXML carries
`w:gridSpan` (confirmed reading `gridSpan=2` off a merged header cell), but
`TableCoordinate` holds only `table_id`, `row`, `col`. Nothing records that
a cell spans multiple columns or rows, so merge changes are undetectable
until extraction captures spans. This is a prerequisite, not a
consequence.

**3. A merged cell already occupies only its anchor.** Extraction dedupes
correctly — a horizontally merged pair produced entries at `col=0` and
`col=1` with no `col=2`. The resulting grid legitimately has holes, and
those holes are what makes merges detectable once spans are captured.

## Decision

A new module, `backend/app/table_diff.py`. None of this fits the existing
paragraph-level pipeline, which has no concept of a grid.

### Stage 1 — reconstruct grids

Group cell paragraphs by `table_id`, index by `(row, col)`, joining the
text of multiple paragraphs occupying one cell. A grid records its cells,
its distinct row indices, its distinct column indices, and each cell's
span. Positions vacated by a merge stay absent rather than being filled.

### Stage 2 — match tables between versions

Match old grids to new grids by flattened cell-text similarity, reusing the
`greedy_match` and embedding machinery that already matches sections and
reconciles moved paragraphs. Unmatched grids mean a whole table was added
or removed, which is out of scope here — those cells continue to report
through the existing per-cell path.

### Stage 3 — diff rows, then columns

Within each matched table pair, match rows by **content similarity** —
`embed_texts` + `cosine_similarity_matrix` + `greedy_match` at a threshold
of `0.85`, the same machinery and threshold `move_reconciliation` already
uses. Unmatched old rows are deletions, unmatched new rows are additions,
and matched rows sitting at different indices are moves, detected with the
same longest-increasing-subsequence logic `detect_section_reordering` uses.
Then diff columns **on the row-aligned grid**, by the identical method.

**Similarity matching, not `difflib.SequenceMatcher`.** This was prototyped
both ways and sequence matching fails outright. On a table where one row was
edited, one moved, and one was added, `SequenceMatcher` over exact row
strings reported the edited row as a delete plus an add, and the moved row
as a delete plus an add — neither ever entered the matched set, so no move
was detectable and the "edited rows stay matched" rule was violated. It
matched only the rows that were both byte-identical and still in order.

Similarity matching handles all three correctly on the same input:

```
matched old#1 -> new#2 (0.96)  EDITED    'Assay | 95%' -> 'Assay | 98%'
matched old#3 -> new#1 (1.00)  MOVED     'Water | 2.0%'
ADDED   new#4                            'Hardness | 8kg'
```

Order matters between the two passes: columns are implicit in this data
model, existing only as a `col` index repeated across rows, so their
content is only comparable once rows line up.

**An edited row stays matched.** If a row's cells were edited, it is still
the same row: it matches, and its cell edits flow through the existing
per-cell path untouched. Only genuinely new or removed rows produce
structural changes. Treating an edited row as a delete plus an add would
make editing one cell of a wide row noisier than it is today — the
opposite of this feature's purpose. The same rule applies to columns.

### Stage 4 — compare merge spans

For each cell position present in both matched grids, compare
`row_span`/`col_span`. A difference is a merge or unmerge.

### Suppression: one structural edit, one row

A row addition reports as a single `table_row_added` carrying the whole
row's content, and the per-cell `added_table_content` changes for that row
are suppressed. Deletions, and both column equivalents, behave the same
way.

**The suppression is deliberately narrow.** A cell is suppressed only when
its *sole* reason for changing is that its whole row or column was added or
deleted. A row that moved *and* had a cell edited reports both the move and
the edit. This follows the rule established when moved content was found to
be hiding edits: a structural change must never conceal a content change.
Implemented with the `excluded_paragraph_ids` pattern already used by
`detect_section_added` and `detect_section_deleted`.

### New change types and risk

| Change type | Risk |
|---|---|
| `table_row_added` | Medium |
| `table_row_deleted` | Medium |
| `table_row_moved` | Informational |
| `table_column_added` | Medium |
| `table_column_deleted` | Medium |
| `table_column_moved` | Informational |
| `table_cell_merge_changed` | Informational |

Added and deleted sit at **Medium**, matching the `added_table_content`
they replace, so this feature reorganizes the report without silently
escalating severity across every existing comparison. Moves and merge
changes sit at **Informational**, matching `section_reordered`. Each needs
an explicit `RISK_TABLE` entry — without one they fall through to
`DEFAULT_RISK` of `"Medium"`, which would wrongly promote moves and merges.

## Design per component

### `backend/app/models.py`

`TableCoordinate` gains two fields, both defaulting to `1`:

```python
row_span: int = 1
col_span: int = 1
```

Defaults matter: every existing construction site, every persisted row
reloaded by `repository._row_to_change`, and every PDF/TXT path continues
to work untouched. Spans are used during diffing on `Paragraph` objects and
are **not persisted** — `repository.save_comparison` flattens only
`table_id`/`row`/`col`, and a reloaded `Change` carries spans of `1`, which
is harmless because spans are meaningless on a `Change` row. **No database
migration is required.**

### `backend/app/extraction.py`

**Both spans come from one uniform mechanism: counting grid positions per
`w:tc` element.** `row.cells` returns a merged cell once per grid position
it occupies — once per spanned column for a horizontal merge, once per
spanned row for a vertical one — and every one of those proxies wraps the
same underlying element. So the number of distinct row indices that element
appears at is its row span, and the number of distinct column indices is
its column span.

Verified on a 3×3 table carrying one horizontal and one vertical merge:

```
anchor r0c0  row_span=1 col_span=2   <- horizontal merge
anchor r1c2  row_span=2 col_span=1   <- vertical merge
(all other anchors)  row_span=1 col_span=1
```

This needs no OOXML attribute reading. `w:gridSpan` would give the column
span directly, but `w:vMerge` records only `restart`/`continue` and never a
count, so rows would need counting regardless — and counting covers both
directions with one mechanism rather than two.

**This requires a pre-pass over the table before emitting cells.** The
existing dedupe loop skips repeat occurrences, so at the anchor — the only
place a merged cell is emitted — the positions still to come have not been
seen yet. Build the counts across the whole table first, then emit.

**The pre-pass must hold every cell proxy alive while counting.** lxml only
guarantees a stable `id()` for an element while some Python reference to
its proxy exists, and for a vertical merge python-docx re-derives the
continuation cell's `_tc` through a fresh lookup each time. Comparing by
`id()` without holding references silently reports merged positions as
distinct elements — verified by making exactly that mistake and getting six
elements instead of five on a 3×2 table with one vertical merge. Keep the
proxies in a list for the duration, and key on the element objects
themselves. The existing dedupe loop already guards against this and its
inline comment explains why; the pre-pass must do the same.

### `backend/app/table_diff.py` (new)

Five responsibilities, each independently testable:

- **`build_grids(paragraphs)`** — group cell paragraphs into per-table
  grids keyed by `table_id`.
- **`match_tables(old_grids, new_grids)`** — content-similarity matching,
  returning matched pairs plus unmatched grids on each side.
- **`diff_rows(old_grid, new_grid)`** — added, deleted, matched, and moved
  rows.
- **`diff_columns(old_grid, new_grid, row_alignment)`** — the same for
  columns, over the row-aligned grid.
- **`diff_merges(old_grid, new_grid)`** — span differences at shared
  positions.

### `backend/app/pipeline.py`

After the existing section and paragraph work, run the table diff over the
old and new paragraph lists, append its changes, and add the cells belonging
to added or deleted rows and columns to the exclusion set consulted when
emitting per-cell table changes.

### `backend/app/risk_rules.py`

Seven new `RISK_TABLE` entries per the table above.

### Unaffected

`section_structure.py`, `section_matching.py`, `move_reconciliation.py`,
`paragraph_diff.py`, `regex_detectors.py`, `llm_classifier.py`, `db.py`,
`repository.py`, `export.py`, and the frontend — no changes. The new change
types are ordinary strings flowing through paths that already carry them,
and the Detailed Changes filter dropdown populates dynamically from the
changes present.

## Testing

- A row added → one `table_row_added` carrying the row's cells; the
  per-cell `added_table_content` changes for that row are absent.
- A row deleted → one `table_row_deleted`; per-cell deletions absent.
- A column added and a column deleted → the column equivalents, with their
  per-cell changes suppressed.
- A row moved with content unchanged → `table_row_moved`, no content rows.
- **A row moved whose cell was also edited → both the move and the cell
  edit are reported.** The central false-negative guard.
- A row whose cells were edited but which did not move → matched, no
  structural change, and the cell edits report exactly as they do today.
- Two horizontally merged cells → `table_cell_merge_changed` when the merge
  is introduced, and again when it is removed.
- **Tables matched by content, not id:** a document that inserts an
  unrelated table above an existing one — shifting its `table_id` — still
  diffs the existing table correctly against its counterpart. This is the
  regression guard for the foundational finding above.
- A whole table added or removed → unmatched, and its cells report through
  the existing per-cell path unchanged.
- Grids with merge holes reconstruct without error.
- Every new change type resolves to its intended risk rather than to
  `DEFAULT_RISK`.
- Existing table behaviour on the real corpus is unchanged where no
  structural edit occurred — full backend suite re-run, and the real DOCX
  pairs in `test-documents/docx/` compared before and after to confirm only
  intended reclassifications.

## Out of Scope

- **Whole table added or removed** as a structural change type. Those cells
  continue reporting individually, exactly as today.
- **Fixing the unstable `table_id` shown to reviewers** in the Table Cell
  column. The diff matches tables correctly regardless, but the displayed
  number is left as-is; it is the same family of problem as cascading
  section renumbering and deserves its own decision.
- Row or column resizing, borders, shading, or any other table formatting.
- Nested tables as structural units — a table inside a cell keeps its own
  `table_id` and is diffed as its own table, which falls out of the design
  without special handling.
- Any change to how cell *content* is compared, classified, or risk-rated.
