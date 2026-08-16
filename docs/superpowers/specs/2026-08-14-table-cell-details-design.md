# Table Cell Details in Change Presentation — Design

**Status:** Approved for implementation

## Purpose

An earlier plan added `TableCoordinate(table_id, row, col)` and
`Paragraph.table_position` during DOCX extraction — deliberately
extraction/storage only, with nothing downstream reading it. That plan's
own "Out of Scope" section explicitly named this as future work: "Any new
`Change` type or comparison logic using `table_position` — this is a
separate, not-yet-designed future feature." This is that feature.

Today, when a reviewer sees a table-sourced change in the Detailed Changes
report (`Source: Table`), there's no way to tell *which* table or *which
cell* it came from — only that it's table content. For a document with
multiple tables, or a table with several rows changing at once, this makes
it hard to reason about what actually happened structurally.

## Decision

`Change` gains two new fields, `old_table_position` and
`new_table_position`, both `Optional[TableCoordinate]` (reusing the
existing dataclass, not inventing a new one). Both, not just one — mirrors
the existing `old_page`/`new_page` pattern already on `Change`, and
correctly represents every case:

- An edited cell: both set, identical value (same `table_id`/`row`/`col`
  on both sides — the cell didn't move, its content changed).
- A newly added row/cell: only `new_table_position` set.
- A deleted row/cell: only `old_table_position` set.
- Content that genuinely moved to a different cell (rare): both set, with
  different values.

Computed at the same 4 places `pipeline.py` already computes `source` for
each `Change` it constructs — reading `paragraph.table_position` directly.
For `Body`-sourced changes this is naturally `None`/`None` with zero extra
conditional logic, since a body paragraph's `table_position` is already
`None` by construction (nothing needs to check `source` first).

**Full pipeline**, matching how every other `Change` field is handled:
persisted to SQLite (migration, since `backend/app.db` is a real, live
file with existing rows), included in JSON export as structured data,
included in CSV export and the frontend as one compact formatted column
(not 6 raw sparse columns — most rows are `Body`-sourced and would have
nothing to show).

**Display format**: one new column, `"Table Cell"`. Blank for
`Body`-sourced rows. `"Table {id}, Row {row}, Col {col}"` when
old/new positions are identical (the common case — edited cell, or only
one side populated). `"Table {id}, Row {row}, Col {col} → Table {id}, Row
{row}, Col {col}"` only when the two sides genuinely differ (the rare
moved-cell case). This same compact text format is used in both the
frontend table and the CSV export; JSON export instead emits the full
structured `old_table_position`/`new_table_position` objects (`{table_id,
row, col}` or `null`), since JSON consumers are typically programmatic and
want structured data, not pre-formatted text.

## Design per component

### `backend/app/models.py`

```python
@dataclass
class Change:
    ...  # existing fields unchanged
    old_table_position: Optional[TableCoordinate] = None
    new_table_position: Optional[TableCoordinate] = None
```

### `backend/app/pipeline.py`

At all 4 existing `Change`-construction sites:

- `_build_paragraph_changes` (both the regex-detection loop and the
  `pending_llm_classification` placeholder): pass
  `old_table_position=old_p.table_position,
  new_table_position=new_p.table_position`.
- The moved-paragraph loop (`for mv in moved:`): pass
  `old_table_position=mv.old_paragraph.table_position,
  new_table_position=mv.new_paragraph.table_position`.
- The deleted-paragraph loop (`for p, section in remaining_deletes:`):
  pass `old_table_position=p.table_position, new_table_position=None`.
- The added-paragraph loop (`for p, section in remaining_inserts:`): pass
  `old_table_position=None, new_table_position=p.table_position`.

These values are set once at `Change` construction and, like `source`,
survive the later AI-classification resolution loop untouched — that loop
only rewrites `change_type`/`reason`/`confidence`/`ai_risk_level`.

### `backend/app/db.py`

`changes` table gains 6 nullable `INTEGER` columns:
`old_table_id`, `old_table_row`, `old_table_col`,
`new_table_id`, `new_table_row`, `new_table_col`.

New idempotent migration function, same pattern as the existing
`_ensure_changes_source_column` (gated by `PRAGMA table_info`, adding
missing columns with `ALTER TABLE`), called from `get_connection()` on
every connection open. No backfill needed or possible — existing rows
predate this concept entirely, so they correctly become `NULL` across all
6 columns, verified against the real, live `backend/app.db` file the same
way the `source` migration was.

### `backend/app/repository.py`

`save_comparison`'s INSERT gains the 6 new columns, flattening
`old_table_position`/`new_table_position` into individual ints (`None`
when the position itself is `None`, i.e. `c.old_table_position.table_id if
c.old_table_position else None`, and likewise for `row`/`col`).

`_row_to_change` reconstructs `TableCoordinate` objects from the 6 raw
columns:

```python
old_table_position=(
    TableCoordinate(table_id=row["old_table_id"], row=row["old_table_row"], col=row["old_table_col"])
    if row["old_table_id"] is not None else None
)
```
(and the mirror for `new_table_position`). Presence is signaled by
checking `old_table_id is not None` alone — all 3 values of one side are
always written together, never partially, so this is sufficient.

### `backend/app/export.py`

`to_json`: adds `"old_table_position"`/`"new_table_position"` keys, each
either `{"table_id": c.old_table_position.table_id, "row": ..., "col":
...}` or `null`.

`to_csv`: adds one `"Table Cell"` column via a small formatting helper
(new function in `export.py`) implementing the compact text format
described above, given `Change.old_table_position`/`new_table_position`.

### `frontend/pages/2_Detailed_Changes.py` / `frontend/logic.py`

A new formatting function in `logic.py` (frontend-side — the frontend only
ever receives JSON dicts from the API, never Python `Change`/`TableCoordinate`
objects, so this is a separate implementation from `export.py`'s CSV
helper, not a shared one) implementing the identical compact text format,
operating on the API response's `old_table_position`/`new_table_position`
dict-or-`None` values. The `st.table(...)` row dict gains a `"Table Cell"`
entry, placed immediately after `"Source"` (mirrors how `"Source"` itself
was positioned directly after `"Section"` in the earlier work).

### Unaffected

`section_structure.py`, `risk_rules.py`, `move_reconciliation.py`,
`paragraph_diff.py` — none of these construct `Change` objects or need
table-position awareness. `frontend/pages/3_Review_and_Export.py` — no
change, same reasoning that kept it out of the earlier `source` field
work (it doesn't display `change_type` or per-cell detail today).
`sectioning.py`, `section_matching.py`, extraction (`extraction.py`) —
untouched; `table_position` already exists on `Paragraph`, this plan only
threads the already-extracted data one layer further downstream.

## Testing

- A table cell edited (same position both sides) → `Change.old_table_position
  == Change.new_table_position`, both populated with the correct
  `table_id`/`row`/`col`.
- A new table row added → `old_table_position is None`,
  `new_table_position` populated.
- A table row deleted → `new_table_position is None`, `old_table_position`
  populated.
- A body (non-table) change of any kind → both `None`.
- Table Cell compact-format helper (both the `export.py` and `logic.py`
  implementations): identical old/new position → single position text;
  differing old/new → arrow-separated text; either side `None` → shows
  only the populated side; both `None` → empty string.
- `to_json` emits the correct nested structure or `null` for both fields.
- `to_csv` emits the correct `"Table Cell"` column text.
- Full round-trip through a temp SQLite DB (save → reload) with all 6
  columns intact, AND explicit verification against the real, live
  `backend/app.db` (existing rows correctly become `NULL` across all 6 new
  columns, no data loss on the pre-existing 144+ rows).
- HTTP round-trip via FastAPI `TestClient` against a real DOCX fixture
  with both an edited table cell and an added table row, confirming the
  API response carries the correct `old_table_position`/`new_table_position`
  for each.
- Full backend suite re-run.

## Out of Scope

- Any new comparison/detection logic that reasons about table structure
  beyond what already exists (e.g. detecting "a whole column was added") —
  this plan only surfaces already-computed position data, it doesn't add
  new detection.
- `frontend/pages/3_Review_and_Export.py` — no change, consistent with how
  it already omits `change_type`/`source`-level detail.
- Any change to `PDF`/`TXT` extraction — neither format has table
  structure, `table_position` stays `None` for them exactly as before.
