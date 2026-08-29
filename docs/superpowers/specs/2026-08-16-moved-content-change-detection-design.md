# Movement Must Not Hide Content Changes — Design

**Status:** Approved for implementation

## Purpose

When a paragraph moves from one section to another **and** its text is also
edited, this tool currently reports only that it moved. The content change
is never detected, never risk-rated, and never shown — a false negative in
a GxP document-review tool, where the whole point is that no substantive
change escapes review.

Verified empirically against the real pipeline before writing this spec
(not inferred from reading the code):

```
old: "Compression force shall be maintained at 15 kN."   (in 1.0 Purpose)
new: "Compression force shall be maintained at 18 kN."   (in 2.0 Storage)

reported: moved_paragraph   risk=Medium   confidence=0.95
missing : numeric_change    risk=High
```

The table-content path has the identical defect, and there it is worse
still — an assay acceptance limit relocating and changing from 95.0% to
98.0% reports as a Medium "table content moved" with the numeric change
absent entirely:

```
old: "Assay limit 95.0 percent"   new: "Assay limit 98.0 percent"
reported: moved_table_content   risk=Medium
missing : numeric_change         risk=High
```

**Section-level moves are already correct** and are not part of this work —
verified that a section which is both reordered and edited produces
`section_reordered` (Informational) *and* `numeric_change` (High) as
separate changes. The defect is specific to paragraph-level and
table-content-level moves.

## Root cause

`pipeline.py` has two disjoint paths for changed content:

- **Edited in place:** goes through `_build_paragraph_changes`, which runs
  the regex detectors and then queues any residual difference as a
  `pending_llm_classification` placeholder for AI semantic classification.
- **Moved:** goes through its own `for mv in moved:` loop, which emits one
  `moved_paragraph` or `moved_table_content` change and runs **no content
  detection whatsoever**.

Both broken cases live in that single loop (it branches on `source` to pick
the change type), so one fix covers both.

The defect is worst exactly where it matters most. `reconcile_moves`
matches orphaned deletes to orphaned inserts at a 0.85 cosine-similarity
threshold, so a paragraph carrying a *small* edit — one spec value, one
limit — still reads as a move at ~0.95 confidence and is swallowed. A
heavily rewritten paragraph falls *below* the threshold, is never treated
as a move, and surfaces as `deleted_paragraph` + `added_paragraph`, both of
which are already reported. So the tool is blindest to precisely the small,
high-consequence numeric edits it exists to catch.

## Decision

**Give moved content full detection parity with content that stayed put.**
In the moved loop, after emitting the existing move row, also call the
existing `_build_paragraph_changes` for the moved pair and extend `changes`
with whatever it returns.

`_build_paragraph_changes(section_heading, old_p, new_p)` already returns
`(list[Change], dict[str, list[str]])` and already handles everything this
needs internally:

- runs every regex detector, emitting each detection as its own `Change`
- computes `source` as `"Table" if (old_p.from_table or new_p.from_table)
  else "Body"` — identical to the logic the move row itself uses, so no
  special-casing is required to keep the two consistent
- passes `old_p.table_position` / `new_p.table_position` through to the
  emitted changes
- queues a `pending_llm_classification` placeholder when a residual textual
  difference remains after stripping the regex-detected values, which the
  existing resolution pass at the end of `compare_documents` turns into a
  real AI classification

**A pure move produces zero extra rows.** When the moved text is unchanged,
the regex detectors find nothing and the stripped old/new texts are equal,
so `_build_paragraph_changes` returns an empty change list and an empty
dict. This is a property of the existing function, not something the fix
adds — which is why reuse is the right call rather than a bespoke
detection path.

**The returned `already_detected_by_id` must be merged** into the
pipeline's existing `already_detected_by_id` dict. That dict is what tells
the AI classifier "a numeric change was already detected for this item,
classify only a genuinely distinct additional change." Dropping it would
make the AI restate the numeric change in prose — the same duplicate-
reporting problem in-place edits already avoid.

**Attribution: content-change rows carry `mv.new_section`.** The paragraph
now lives in the new section, so filing its content change there groups it
with every other change in that section on the Detailed Changes page, where
a reviewer reading that section will actually encounter it. The separate
move row keeps its existing compound `"{old_section} -> {new_section}"`
label, so the relocation itself remains fully visible and the two rows
together tell the complete story.

**Risk levels stay separate and unmodified.** The move row remains at its
current risk; the content-change rows carry their own real risk (High for a
numeric change). This is the "captured separately" model: movement no
longer masks severity, because the severity now rides on its own row.

## Design per component

### `backend/app/pipeline.py`

The only file that changes. Inside `compare_documents`, in the existing
`for mv in moved:` loop, after the `changes.append(Change(...))` that emits
the move row, add:

```python
moved_content_changes, moved_already_detected = _build_paragraph_changes(
    mv.new_section, mv.old_paragraph, mv.new_paragraph
)
changes.extend(moved_content_changes)
already_detected_by_id.update(moved_already_detected)
```

Placement matters in one respect only: this must run before the
`pending_llm_classification` resolution block at the end of
`compare_documents`, so the placeholders it queues get resolved. The moved
loop already sits above that block, so no reordering is needed.

### Unaffected

`move_reconciliation.py` — the 0.85 threshold and the matching itself are
unchanged; this fix is about what happens *after* a move is identified, not
about which pairs qualify as moves. `section_structure.py`,
`regex_detectors.py`, `llm_classifier.py`, `extraction.py`, `db.py`,
`repository.py`, `export.py`, and the frontend — no changes; the new rows
are ordinary `Change` objects flowing through paths that already exist.

## Testing

- A paragraph that moves between sections **and** has a numeric edit →
  both `moved_paragraph` and `numeric_change` are reported, as separate
  changes.
- The `numeric_change` from that move carries the **new** section heading,
  not the old one and not the compound `"old -> new"` label.
- The `numeric_change` from that move carries `ai_risk_level` "High" — i.e.
  the real severity, not the move row's default.
- Table content that moves **and** has a numeric edit → both
  `moved_table_content` and `numeric_change`, with `source == "Table"` and
  the table position preserved on the content-change row.
- **A pure move with identical text produces exactly one change** (the move
  row) and no spurious content-change rows — the regression guard proving
  this fix does not duplicate-report unchanged relocations.
- A moved paragraph whose only change is semantic (no numeric/unit/date
  difference) queues a `pending_llm_classification` placeholder, which the
  existing resolution pass converts into an AI-classified change.
- A moved paragraph carrying **both** a numeric edit and a residual
  semantic edit emits `numeric_change` *and* a
  `pending_llm_classification`, and the `already_detected` hint for that
  placeholder contains `["numeric_change"]` — so the AI is told not to
  restate what the regex already caught. Note this hint only exists when a
  residual semantic difference remains: a *purely* numeric edit emits just
  `numeric_change` with no placeholder and no hint entry, because the regex
  detection fully explains the difference (verified empirically against
  `_build_paragraph_changes` before writing this spec).
- Full backend suite re-run to confirm no regressions, with particular
  attention to existing move tests, which must continue to pass unchanged
  for pure moves.

## Out of Scope

- **`moved_paragraph` / `moved_table_content` risk levels.** Neither
  appears in `RISK_TABLE`, so both fall back to the `DEFAULT_RISK` of
  "Medium". Whether a relocation should carry its own considered risk
  rating is a real question, but a pre-existing and orthogonal one — this
  spec deliberately leaves those values untouched so the change under
  review is only "stop hiding content changes."
- **The 0.85 move-matching threshold.** Tuning what counts as a move is a
  separate concern with its own false-positive/false-negative tradeoffs.
- **Section-level move detection**, which was verified already correct.
- **Pairing the move row and its content rows in the UI.** They are related
  but independently listed; visually linking them on the Detailed Changes
  page is a presentation question for a future iteration.
