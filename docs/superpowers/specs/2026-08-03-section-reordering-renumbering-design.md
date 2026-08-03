# Section Reordering & Renumbering Detection — Design

**Status:** Approved for implementation

## Purpose

Section-level comparison today is purely content-based: `section_matching.py`
matches old and new sections by embedding similarity, and `pipeline.py` only
diffs the body paragraphs of matched sections. Two real signals fall through
entirely as a result:

- **Renumbering** — a matched section's heading number changes (e.g.
  `"2.0 Acceptance Criteria"` → `"3.0 Acceptance Criteria"`, typically because
  a section was inserted or removed earlier in the document). `Section.heading`
  is never diffed anywhere — only `Section.paragraphs` (the body) is. A pure
  renumber produces zero `Change` today.
- **Reordering** — a matched section's position relative to its siblings
  changes (e.g. two sections swap places). `match.old_index` and
  `match.new_index` are computed by `section_matching.py` but never compared
  anywhere. Matching is by design position-independent (so a moved section's
  body isn't misdiffed against unrelated neighboring content), but the fact
  that it moved is never itself reported.

## Decision

Add two new, independent `Change.change_type` values, both risk
`"Informational"`:

- **`section_renumbered`** — fires when a matched section's heading number
  prefix changes but the rest of the heading text is identical. Any other
  kind of heading wording change (with or without a number change) is **out
  of scope** for this feature and stays undetected, same as today — it can be
  a separate future feature ("heading rewording detection").
- **`section_reordered`** — fires when a matched section's position changed
  *relative to the other matched sections*, ignoring pure index shifts caused
  by insertions/deletions elsewhere. Inserting one new section must not
  falsely flag every section after it as "reordered."

A section can receive both a `section_renumbered` and a `section_reordered`
`Change` in the same comparison — they are independent checks, not mutually
exclusive, since a document edit can renumber a section, move it, both, or
neither.

**Why Informational risk:** these are structural/cosmetic signals, not
content changes — same tier as `formatting_only`. Content inside the section
is still classified normally and separately through the existing pipeline;
this feature only adds visibility into structural drift, it doesn't change
how content changes are risk-classified.

## Design per component

### `backend/app/section_structure.py` (new module)

Mirrors the codebase's existing one-file-per-concern pattern
(`section_matching.py`, `move_reconciliation.py`, `paragraph_diff.py`).

```python
def detect_section_renumbering(
    matches: list[SectionMatch],
    old_sections: list[Section],
    new_sections: list[Section],
) -> list[Change]: ...

def detect_section_reordering(
    matches: list[SectionMatch],
    old_sections: list[Section],
    new_sections: list[Section],
) -> list[Change]: ...
```

**Renumbering algorithm:** a regex extracts a leading number and the
remainder text from a heading:

```
^(?P<num>\d+(?:\.\d+)*)\s+(?P<rest>.*)$
```

For each matched pair, apply the regex to both `old_sections[m.old_index].heading`
and `new_sections[m.new_index].heading`. If both match, `num` differs, and
`rest` is identical after collapsing whitespace, emit a `section_renumbered`
`Change`. Headings where either side doesn't match the pattern (no
detectable leading number) are silently skipped — no false positive; this
only fires for the same numbered-heading style `sectioning.py`'s structural
detection already recognizes.

**Reordering algorithm:** take `matches` sorted by `old_index`, and look at
the sequence of their `new_index` values. Compute the **longest increasing
subsequence (LIS)** of that sequence. Matches in the LIS are considered
"still in relative order"; every match *not* in the LIS is a true reorder —
its position relative to the sections around it changed, not just shifted by
an insertion/deletion elsewhere. This is what makes the detector immune to
index-shift noise: inserting a new section uniformly increments every later
`new_index` without breaking their relative order, so LIS includes all of
them and nothing is falsely flagged.

For each match not in the LIS, emit a `section_reordered` `Change` with a
reason citing concrete document positions, e.g.:

```
f"Section moved from position {m.old_index + 1} to position {m.new_index + 1} in the document."
```

(1-indexed for readability.) The LIS decides *whether* to fire; the reason
text still reports the real positions for a reviewer's benefit.

**Change construction (both detectors):**
- `section`: the section's heading text (new heading for renumbering, since
  that's the current name; either heading for reordering, since heading text
  is unchanged — use the new heading for consistency).
- `old_text` / `new_text`: old/new heading text.
- `old_page` / `new_page`: `None`. A section-level structural signal doesn't
  map to one paragraph's page, and `Section` doesn't carry a page for its
  heading (only individual `Paragraph`s do) — not changing that model for
  this feature.
- `confidence`: `1.0` (rule-based, not probabilistic).
- `source`: naturally `"Body"` — these are derived from `Section.heading`,
  never from table content.
- `ai_risk_level`: via `risk_rules.assign_risk(change_type)`.

### `backend/app/risk_rules.py`

Add to `RISK_TABLE`:
```python
"section_renumbered": "Informational",
"section_reordered": "Informational",
```

### `backend/app/pipeline.py`

Immediately after `match_result = section_matching.match_sections(...)` in
`compare_documents`, call both new detectors and extend `changes` with their
results, before the existing per-section paragraph-diffing loop:

```python
changes.extend(section_structure.detect_section_renumbering(
    match_result.matches, old_sections, new_sections
))
changes.extend(section_structure.detect_section_reordering(
    match_result.matches, old_sections, new_sections
))
```

### Unaffected

`section_matching.py`, `paragraph_diff.py`, `move_reconciliation.py`,
`sectioning.py`, `regex_detectors.py`, `llm_classifier.py` — no changes.
`export.py` and the frontend — no changes; both new `change_type` strings
flow through the existing `Change` → DB → export → Detailed Changes table
path unmodified, exactly like every other `change_type` string already does.

## Testing

- Pure renumber (heading number changes, rest of heading and body identical)
  → `section_renumbered`, reason names old/new numbers.
- Reworded heading (non-numeric text differs, with or without a number
  change) → no `section_renumbered` — regression guard proving this doesn't
  over-fire on general heading edits.
- A heading with no numbered prefix on either side → no `section_renumbered`
  — regression guard for ALL-CAPS-style headings.
- A section inserted between two others → no `section_reordered` for the
  untouched sections despite their raw `new_index` shifting — regression
  guard for the LIS-based logic specifically (this is the core correctness
  property of the feature).
- Two sections genuinely swapped → both flagged `section_reordered`, reason
  cites real before/after positions.
- A section that is both renumbered and reordered in the same comparison →
  both `Change`s present, independently, proving the two checks don't
  interfere with each other.
- `risk_rules.assign_risk("section_renumbered")` and
  `assign_risk("section_reordered")` both return `"Informational"`.
- Full backend suite re-run to confirm no regressions.

## Out of Scope

- General heading rewording detection (any heading text change beyond a pure
  number-prefix swap) — a separate, not-yet-requested future feature.
- Any position/number signal for unmatched (deleted/inserted) sections —
  those already produce their own delete/insert changes; this feature only
  concerns sections that matched between old and new.
- Any frontend UI change (e.g. a dedicated "Structure Changes" view) — the
  existing Detailed Changes table already surfaces every `change_type`
  uniformly; no new display is being requested.
