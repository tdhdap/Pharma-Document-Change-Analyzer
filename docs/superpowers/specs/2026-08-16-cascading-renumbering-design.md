# Cascading vs Deliberate Section Renumbering — Design

**Status:** Approved for implementation

## Purpose

Adding or deleting one section renumbers every numbered section after it,
and the tool currently reports each of those as an independent
`section_renumbered` change. Verified on the real pipeline: inserting a
single section into a five-section document produced **four** changes —
one `section_added` and three `section_renumbered` rows:

```
section_renumbered   '3.0 Equipment' -> '4.0 Equipment'
section_renumbered   '4.0 Procedure' -> '5.0 Procedure'
section_renumbered   '5.0 Records'   -> '6.0 Records'
section_added        '3.0 Safety Precautions'
```

In a forty-section SOP, inserting one section near the top would generate
roughly thirty-seven such rows. All of them are mechanical consequences of
a single editorial act, and they bury the one row that matters.

## The rule

For each renumbered section, compute the shift its number *should* have if
nothing deliberate happened:

```
expected_shift = (numbered sections inserted above it)
               - (numbered sections deleted above it)
```

- Number moved by exactly `expected_shift` (and `expected_shift != 0`)
  → **cascading**
- Number moved by any other amount → **deliberate**

"Above it" means earlier in document order: inserted sections are counted
by their index in the new document relative to this section's new index;
deleted sections by their index in the old document relative to its old
index. Only sections whose heading actually parses as numbered are counted
— pseudo-sections the tool generates (`Page Header`, `Text Box 1`,
`Footnote 1`, `Preamble`) carry no number and must not affect the
arithmetic.

Verified against five scenarios before writing this spec:

| Scenario | expected | actual | verdict |
|---|---|---|---|
| Section inserted above | +1 | +1 | cascading |
| Section deleted above | −1 | −1 | cascading |
| Two sections swapped | 0 | +1 | deliberate |
| `3.0` → `3.5` | 0 | 0 | deliberate |
| Gapped doc (1.0, 2.0, **4.0**) + insertion | +1 | +1 | cascading |

**Why arithmetic rather than position.** An intuitive alternative — "a
section's number should equal its position, so a number that still matches
its position is mechanical" — fails on the gapped-document row above,
where `4.0` sits at position 3. Real SOPs accumulate numbering gaps.
Comparing against what *structurally changed* rather than against position
handles that correctly.

**Swaps are deliberate under this rule.** Two sections trading places
produces `expected_shift = 0` with a non-zero actual shift, so both stay
`section_renumbered`. This was a deliberate scope decision: the request was
specifically about renumbering caused by an addition or deletion, and
`detect_section_reordering` already reports the swap itself.

## Decision

**Emit a distinct change type, `section_renumbered_cascade`, rather than
suppressing anything.** The Detailed Changes page already has a "Filter by
change type" dropdown, so a distinct type lets a reviewer hide cascades in
one click while they remain present in the report, in export, and in the
counts by default. This reuses machinery that already exists and hides
nothing without an explicit user action.

Rejected alternatives: suppressing cascades entirely (hides rows by
default, and this project's standing priority is minimizing false
negatives); collapsing them into one summary row (loses the per-section
rows the reviewer-comment and accept workflow attaches to).

**Risk stays `Informational`,** matching `section_renumbered`. A cascade is
not more or less risky than the renumbering it already was — the point of
this change is filterability, not reprioritization.

## Safety against false negatives

This design cannot hide a real change, for three independent reasons:

1. **Nothing is suppressed.** A cascading renumber is still a row with full
   old/new heading text. Only its label changes. Even a misclassification
   therefore hides nothing — it mislabels a visible row.

2. **Doubt resolves to "deliberate".** The classification only downgrades
   when the arithmetic matches exactly. Everything else stays
   `section_renumbered`: gapped numbering that doesn't line up,
   sub-numbering like `3.1` → `3.2` (the shift is at a deeper component
   than the top-level counting models), headings whose number fails to
   parse, and any shift that isn't exactly `expected_shift`. The rule
   over-reports rather than under-reports by construction.

3. **Other detectors are unaffected.** Verified on the real pipeline that a
   section which is cascaded *and* has its wording changed *and* has its
   body content changed still produces every row independently:

   ```
   section_renumbered       Informational   (becomes the cascade type)
   section_heading_changed  Medium          <- still reported
   numeric_change           High            <- still reported
   section_added            High            <- the real change
   ```

   The cascade classification touches only which of two labels the
   renumbering row carries.

## Design per component

### `backend/app/section_structure.py`

`detect_section_renumbering` needs the inserted and deleted section indices
to do the counting; it does not receive them today. Extend its signature
with two parameters, both defaulting to `None` so any existing direct
caller keeps working:

```python
def detect_section_renumbering(
    matches: list[SectionMatch],
    old_sections: list[Section],
    new_sections: list[Section],
    inserted_indices: list[int] | None = None,
    deleted_indices: list[int] | None = None,
) -> list[Change]:
```

Inside the existing loop, after establishing that `old_num != new_num`,
compute the expected shift and compare it to the actual top-level shift.
Only the first dot-separated component participates: a top-level insertion
shifts the first component and leaves the rest alone, and restricting the
comparison this way is what keeps sub-numbering shifts classified as
deliberate.

When the two match and the expected shift is non-zero, emit
`change_type = "section_renumbered_cascade"` with a reason naming the
cause; otherwise keep `"section_renumbered"` and its existing reason
unchanged.

Reason text for the cascade case states the mechanism plainly, e.g.:

```
Section renumbered from '3.0' to '4.0' as a side effect of 1 section added above it; wording unchanged.
```

with `added`/`removed` and the count varying by the sign and magnitude of
the expected shift. The `; wording unchanged.` clause is accurate because
any wording change is reported separately by
`detect_section_heading_changed` — the two detectors already co-fire
independently, which was verified earlier in this project.

A number component that fails to parse as an integer (`int()` raising)
means the arithmetic cannot be trusted, and the change stays
`section_renumbered`.

### `backend/app/risk_rules.py`

Add one entry, matching the existing `section_renumbered` value:

```python
"section_renumbered_cascade": "Informational",
```

Without it the type would fall through to `DEFAULT_RISK` of `"Medium"`,
silently promoting cascades above the renumbering they replace — the
opposite of the intent.

### `backend/app/pipeline.py`

Pass the two new arguments at the single existing call site:

```python
    changes.extend(section_structure.detect_section_renumbering(
        match_result.matches, old_sections, new_sections,
        match_result.inserted_indices, match_result.deleted_indices,
    ))
```

`SectionMatchResult` already carries `inserted_indices` and
`deleted_indices` (`backend/app/models.py:37-40`), so no new plumbing is
needed to obtain them.

### Unaffected

`detect_section_reordering`, `detect_section_added`,
`detect_section_deleted`, `detect_section_heading_changed` — untouched.
`section_matching.py`, `models.py`, `db.py`, `repository.py`,
`export.py`, and the frontend — no changes; `change_type` is an existing
string field and the frontend's change-type filter is populated
dynamically from the changes present, so the new type appears in the
dropdown automatically.

## Testing

- A section inserted above → following sections report
  `section_renumbered_cascade`, and the `section_added` row still reports
  normally.
- A section deleted above → following sections report
  `section_renumbered_cascade` with a reason naming a removal.
- Two sections swapped with no addition or deletion → both stay
  `section_renumbered`.
- A deliberate `3.0` → `3.5` with no structural change → stays
  `section_renumbered`.
- A gapped document (1.0, 2.0, 4.0) with an insertion → `4.0` → `5.0`
  reports as cascading, proving the rule does not depend on numbers
  matching positions.
- Sub-numbering `3.1` → `3.2` → stays `section_renumbered` (the
  conservative default).
- A cascaded section that *also* has its wording changed still produces a
  separate `section_heading_changed`, and one whose body content changed
  still produces its own content change — the cascade label suppresses
  nothing.
- Pseudo-sections (`Page Header`, `Text Box 1`, `Footnote 1`) inserted or
  deleted above a numbered section do **not** count toward
  `expected_shift`, since they carry no number.
- `risk_rules.assign_risk("section_renumbered_cascade") == "Informational"`,
  pinning it against the `DEFAULT_RISK` fallback.
- Calling `detect_section_renumbering` without the two new arguments
  behaves exactly as before — every renumbering reports as
  `section_renumbered`.
- Full backend suite re-run; existing renumbering tests must still pass
  unchanged, since none of them involve an addition or deletion above the
  renumbered section.

## Out of Scope

- **Cascades at sub-numbering levels** (`3.1` → `3.2` caused by inserting
  `3.1`). The counting models top-level shifts only; deeper levels stay
  classified as deliberate, which over-reports rather than hides.
- **Treating move-driven renumbering as cascading.** Decided against
  above; `detect_section_reordering` already reports the move.
- **Collapsing cascades into a single summary row**, and **suppressing
  them by default** — both rejected in the Decision section.
- **Any change to risk levels of existing change types**, or to the other
  four section detectors.
