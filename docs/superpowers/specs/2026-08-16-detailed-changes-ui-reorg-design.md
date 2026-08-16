# Detailed Changes UI Reorganization — Design

**Status:** Approved for implementation

## Purpose

The Detailed Changes page (`frontend/pages/2_Detailed_Changes.py`) currently
renders every change as one row in a single flat `st.table()`, regardless
of which document section it came from, whether it's a body or table
change, or how risky it is. For a document with a dozen-plus changes
spanning several sections, a mostly-empty "Table Cell" column (blank for
every non-table row), duplicated section names repeated down the first
column, and no way to collapse anything makes it hard to scan — a
reviewer has to read every row to find what matters. This redesigns the
page into a hierarchy that matches how a reviewer actually approaches a
revised SOP: check the boilerplate (headers/footers), read the body,
then check the tables, drilling into one document section at a time.

## Decision

**Four fixed top-level groups, always shown in this order: Headers →
Footers → Body → Tables.** All four render even when empty (e.g.
"Footers — 0 changes", collapsed) — in a compliance tool, seeing that a
category was checked and found clean is itself useful information; a
category that silently doesn't appear could read as "the tool didn't
check this" rather than "nothing changed here."

**Category assignment**, applied to every change independently of the
others:
- **Headers** — `section` starts with `"Page Header"` (covers every
  header variant already produced by the backend: default, first-page,
  even-page, multi-section-qualified).
- **Footers** — `section` starts with `"Page Footer"`, same reasoning.
- **Tables** — `source == "Table"`, regardless of which section it
  originated in. Pulled out into its own top-level group rather than
  staying embedded in whichever section produced it, since table data
  (e.g. a batch parameter table) is often the most safety-critical
  content in a pharma SOP and deserves its own clearly-separated view
  rather than being one sparse-columned row among prose changes.
- **Body** — everything else: regular numbered sections (`"2.0 Scope"`,
  `"4.0 Procedure"`, ...), `"Text Box N"` pseudo-sections, and
  `"Footnote N"` pseudo-sections. Table membership is decided by
  `source`, not by category, so a change is Table-categorized even if its
  `section` value looks like a Text Box or Footnote pseudo-heading (rare,
  since a text box or footnote can itself contain a table per this
  project's existing extraction support, but must still land in Tables
  for consistency with every other table change).

Category assignment is a pure function of each change's own `section` and
`source` fields — no cross-referencing against the comparison's other
changes is needed, so it's a simple per-row classification, not a
multi-pass grouping decision.

**Nesting.** Headers and Footers list their changes directly (a body-style
table, no further breakdown) — there are typically only one or two header
or footer variants in a document, so a second level of nesting would add
clicks without reducing what's on screen. Body and Tables both break down
one level further: one collapsible sub-group per originating document
section (`"2.0 Scope"`, `"4.0 Procedure"`, `"Text Box 1"`, ...), in
document order, using the same section list order the backend already
produces (the order sections first appear across all of a comparison's
changes, which is itself document order since paragraph indices are
assigned in extraction order).

**Section/category header format**, applied at both the top level and the
nested section level: name, total count, and a risk breakdown with one
emoji-colored badge per risk tier present among its changes — 🔴 High,
🟡 Medium, 🟢 Low, ⚪ Informational — e.g. `🔴 4.0 Procedure — 5 changes (3
High, 2 Medium)`. A category or section is expanded by default if it
contains at least one High-risk change; otherwise it starts collapsed.
This means opening the page immediately surfaces everything urgent without
a wall of pre-opened tables for routine changes.

**Columns.**
- Body-style tables (Headers, Footers, and each Body sub-group): Old Text,
  New Text, Change Type, Risk, Reason. No Source or Table Cell column —
  both are now implied by which group/category the row is already in.
- Table-style tables (each Tables sub-group): Table ID, Row, Col, Old
  Text, New Text, Change Type, Risk, Reason. Row/Col show the single
  current position for the overwhelming common case (an edited, added, or
  deleted cell — old and new position identical or one side absent). In
  the rare case where a cell's content genuinely moved to a different
  coordinate, both are shown inline in the same cell as `"Row 1 → Row
  3"`/`"Col 0 → Col 2"` rather than doubling the column count for a case
  that almost never occurs — mirrors the already-established compact
  format in `format_table_cell` (arrow-separated only when old/new
  differ).

**Filters.** The existing risk/section/change-type filters
(`st.selectbox`) stay exactly where they are, above the grouped view, and
keep working exactly as today via the existing `filter_changes()` — they
now filter the flat change list *before* it's grouped into categories, so
a category or section left with zero matching changes after filtering
simply shows "0 changes" (still visible, per the always-show-four-groups
decision above) rather than disappearing.

## Design per component

### `frontend/logic.py`

**New function**, decides which of the four categories a single change
belongs to. `source == "Table"` is checked first — a header/footer's own
table-sourced changes (rare, but possible per this project's existing
extraction support) must still land in "Tables", not "Headers"/"Footers",
per the Decision section above:

```python
def categorize_change(change: dict) -> str:
    if change.get("source", "Body") == "Table":
        return "Tables"
    section = change["section"]
    if section.startswith("Page Header"):
        return "Headers"
    if section.startswith("Page Footer"):
        return "Footers"
    return "Body"
```

**New function**, groups an already-filtered change list into the
four-category structure, each with its risk breakdown and (for Body/
Tables) its per-section breakdown:

```python
def group_changes_for_display(changes: list[dict]) -> dict:
    """Returns a dict with keys 'Headers', 'Footers', 'Body', 'Tables', in
    that fixed order (dict insertion order, relied on by the page). Each
    value is {'changes': [...], 'risk_counts': {...}} for Headers/Footers,
    or {'sections': {section_name: {'changes': [...], 'risk_counts':
    {...}}}, 'risk_counts': {...}} for Body/Tables, with sections in
    document order (first-seen order across the input list)."""
```

(Full implementation with exact dict shape, risk-count computation reusing
`c.get("reviewer_risk_level") or c["ai_risk_level"]` — the same risk
resolution already used by `filter_changes` — specified in the
implementation plan.)

**Existing `format_table_cell`** — superseded by the new per-column Row/Col
display in the Tables sub-tables and no longer called from
`2_Detailed_Changes.py`. Left in place (still may be used elsewhere, and
removing it is out of scope for a UI reorganization) but no longer part of
this page's rendering path.

### `frontend/pages/2_Detailed_Changes.py`

Restructured to: apply the existing filters to get the flat change list
(unchanged), call `group_changes_for_display`, then render each of the
four categories via `st.expander` with the risk-badge header format,
containing either a single `st.table` (Headers/Footers) or a nested
`st.expander` per section (Body/Tables) each containing its own
`st.table`. Full step-by-step rendering code specified in the
implementation plan.

### Unaffected

Backend (`app/`) — no changes; this reorganization works entirely from
data the API already returns. `1_Change_Summary.py`, `3_Review_and_Export.py`
— no changes. `filter_changes`, `build_change_update_payload` — unchanged,
reused as-is.

## Testing

- `categorize_change`: a `"Page Header"` change → `"Headers"`; a `"Page
  Header (Section 2, First Page)"` change → `"Headers"`; a `"Page Footer"`
  change → `"Footers"`; a table-sourced change whose `section` is a
  regular numbered section → `"Tables"`; a table-sourced change whose
  `section` is `"Text Box 1"` → `"Tables"` (not `"Body"`); a table-sourced
  change whose `section` starts with `"Page Header"` → `"Tables"` (not
  `"Headers"` — proves the check order from the Decision section); a
  body-sourced change in a regular numbered section → `"Body"`; a
  body-sourced change in `"Text Box 1"` → `"Body"`; a body-sourced change
  in `"Footnote 1"` → `"Body"`.
- `group_changes_for_display`: all four keys always present even when a
  category has zero changes; sections within Body/Tables appear in
  first-seen (document) order, not alphabetical; risk-count breakdown at
  both the category and section level matches the actual changes present;
  a change with a reviewer-overridden risk level (`reviewer_risk_level`
  set) is counted under that overridden risk, not the original
  `ai_risk_level` (matching `filter_changes`'s existing resolution rule).
- Manual verification in the browser: load a real comparison result (the
  `AllFeaturesDemo_v1`/`v2` pair already covers Headers, a Body change, a
  Table change, a Text Box change, and a Footnote change in one document),
  confirm the four groups appear in order, confirm High-risk sections/
  categories start expanded and others don't, confirm filters still narrow
  results correctly within the new structure.

## Out of Scope

- Any change to how risk levels are computed or assigned (`risk_rules.py`)
  — this is presentation only.
- Sorting sections or categories by risk instead of document order — the
  fixed Headers→Footers→Body→Tables order and document order within
  Body/Tables was a deliberate choice (mirrors how a reviewer reads the
  document); the risk badge is what surfaces urgency without reordering.
- Any change to the Review & Export page's editing table, which remains a
  flat `st.data_editor` — this reorganization is scoped to the read-only
  Detailed Changes view.
- Persisting expand/collapse state across page reloads — Streamlit's
  default expander behavior (resets on rerun) is accepted as-is.
