# Section Heading Changed Detection — Design

**Status:** Approved for implementation

## Purpose

`section_renumbered` (shipped earlier) only fires on a *pure* number swap —
the leading number changes, the rest of the heading text stays byte-for-byte
identical. Any heading that gets reworded — with or without its number also
changing, or a heading that has no number at all — produces zero structural
signal today, even though the section itself still matched between old and
new documents. A reviewer has no way to see "this section's title changed
meaning" unless the wording change happens to also touch the body content.

## Decision

One new `Change.change_type`, `"section_heading_changed"`, risk `"Medium"`
— higher than the purely cosmetic `section_renumbered`/`section_reordered`
(`"Informational"`), since rewording a heading can signal a real conceptual
change to what the section covers (e.g. "Deviation Handling" →
"Non-Conformance Management"), not just a numbering artifact.

**`detect_section_renumbering` changes its own behavior**, not just gains a
sibling. Today it requires the non-numeric part of the heading (the
"wording") to stay identical — `old_num == new_num or old_rest !=
new_rest` skips detection. That second half of the condition is removed:
renumbering now fires whenever the leading number differs, **regardless of
whether the wording also changed**. This is a deliberate behavior change to
already-shipped code, confirmed with the user — not an oversight. The
existing test `test_number_and_wording_both_changing_is_not_flagged_as_pure_renumbering`
currently asserts nothing fires when both change together; it is rewritten
to assert `section_renumbered` *does* fire in that case (its name changes
accordingly, since "not flagged" is no longer true).

**Net effect, by case:**

| Number | Wording | Result |
|---|---|---|
| unchanged | unchanged | nothing |
| changed | unchanged | `section_renumbered` only (pure renumber) |
| unchanged | changed | `section_heading_changed` only |
| changed | changed | **both** — `section_renumbered` AND `section_heading_changed`, two separate rows for the one heading |
| no number on either/both sides | changed | `section_heading_changed` only (nothing to renumber) |

The two detectors are independent, not mutually exclusive — a heading that
changes in both dimensions produces two rows, each carrying its own
specific fact (what number it was renumbered from/to; what the heading
wording changed from/to), rather than one detector suppressing the other or
one row trying to describe both facts at once.

## Design per component

### `backend/app/section_structure.py`

**`detect_section_renumbering` (modify existing function):**
```python
def detect_section_renumbering(
    matches: list[SectionMatch],
    old_sections: list[Section],
    new_sections: list[Section],
) -> list[Change]:
    changes: list[Change] = []
    for m in matches:
        old_heading = old_sections[m.old_index].heading
        new_heading = new_sections[m.new_index].heading
        old_split = _split_heading_number(old_heading)
        new_split = _split_heading_number(new_heading)
        if old_split is None or new_split is None:
            continue
        old_num, old_rest = old_split
        new_num, new_rest = new_split
        if old_num == new_num:
            continue
        change_type = "section_renumbered"
        changes.append(Change(
            change_id=str(uuid.uuid4()), section=old_heading, change_type=change_type,
            old_text=old_heading, new_text=new_heading, old_page=None, new_page=None,
            confidence=1.0, ai_risk_level=risk_rules.assign_risk(change_type),
            reason=f"Section renumbered from '{old_num}' to '{new_num}'.", source="Body",
        ))
    return changes
```
(Only the condition on the `continue` line changes — `if old_num == new_num
or old_rest != new_rest:` becomes `if old_num == new_num:`. `old_rest`/
`new_rest` are still computed via the unpack, just no longer consulted by
the guard; the reason text and every other field is untouched.)

**`detect_section_heading_changed` (new function):**
```python
def detect_section_heading_changed(
    matches: list[SectionMatch],
    old_sections: list[Section],
    new_sections: list[Section],
) -> list[Change]:
    changes: list[Change] = []
    for m in matches:
        old_heading = old_sections[m.old_index].heading
        new_heading = new_sections[m.new_index].heading
        if old_heading == new_heading:
            continue
        if is_synthetic_heading(old_heading) or is_synthetic_heading(new_heading):
            continue
        old_split = _split_heading_number(old_heading)
        new_split = _split_heading_number(new_heading)
        if old_split is not None and new_split is not None:
            _, old_rest = old_split
            _, new_rest = new_split
            if old_rest == new_rest:
                continue
        change_type = "section_heading_changed"
        changes.append(Change(
            change_id=str(uuid.uuid4()), section=old_heading, change_type=change_type,
            old_text=old_heading, new_text=new_heading, old_page=None, new_page=None,
            confidence=1.0, ai_risk_level=risk_rules.assign_risk(change_type),
            reason=f"Section heading changed from '{old_heading}' to '{new_heading}'.",
            source="Body",
        ))
    return changes
```

Reuses the existing (already-private, same-module) `_split_heading_number`
and `is_synthetic_heading` helpers — no new parsing logic duplicated.

### `backend/app/risk_rules.py`

Add to `RISK_TABLE`:
```python
"section_heading_changed": "Medium",
```

### `backend/app/pipeline.py`

Alongside the existing renumbering/reordering/added/deleted calls (all
already run right after `section_matching.match_sections(...)`), add:
```python
changes.extend(section_structure.detect_section_heading_changed(
    match_result.matches, old_sections, new_sections
))
```

### Unaffected

`detect_section_reordering`, `detect_section_added`, `detect_section_deleted`
— unchanged; heading-text comparison is independent of position and of
whole-section add/delete detection. `move_reconciliation.py`,
`paragraph_diff.py`, `export.py`, frontend — no changes; the new type flows
through the existing generic path.

## Testing

- Pure renumber (number changes, wording identical) → `section_renumbered`
  only, `section_heading_changed` returns nothing for that match —
  regression guard for the "one signal, not both" case.
- Pure rewording (number identical, wording changes) → `section_heading_changed`
  only, `section_renumbered` returns nothing for that match (your literal
  example from the request).
- Both number and wording change together → **both** detectors fire for
  the same match — `detect_section_renumbering` returns one
  `section_renumbered` change, `detect_section_heading_changed` returns one
  `section_heading_changed` change, independently. This rewrites
  `test_number_and_wording_both_changing_is_not_flagged_as_pure_renumbering`
  (renamed to reflect the new expected behavior) plus adds the mirror
  assertion on the heading-changed side.
- A non-numbered heading (ALL-CAPS style) that gets reworded →
  `section_heading_changed` fires (no number to renumber, so
  `section_renumbered` correctly stays silent for it).
- Identical headings → neither detector fires.
- Synthetic headings (`"Preamble"`/`"Paragraph N"`) that "change" due to a
  document being headingless → neither detector fires — regression guard
  mirroring the same property already required of the other three
  detectors.
- `risk_rules.assign_risk("section_heading_changed")` returns `"Medium"`.
- A pipeline-level integration test proving all three signals (renumbered,
  heading-changed, and an ordinary body-content change in the same
  section) can appear together for one document comparison without
  interfering with each other.
- Full backend suite re-run — in particular every existing
  `test_section_structure.py` and `test_pipeline.py` test involving
  `section_renumbered` must still pass with the relaxed condition, since
  none of them exercise the "wording also changed" case that used to
  suppress it.

## Out of Scope

- Any change to `section_reordered`, `section_added`, `section_deleted` —
  already correct, no interaction with heading-wording changes.
- Semantic classification of *what kind* of wording change occurred (e.g.
  distinguishing a typo fix from a genuine scope change) — this is a
  structural presence/absence signal only, same tier as the other three;
  AI-based classification of heading changes is a separate, not-yet-requested
  feature.
