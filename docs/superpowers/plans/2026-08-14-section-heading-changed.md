# Section Heading Changed Detection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect a matched section's heading wording changing — independent of whether its leading number also changed — as a new `section_heading_changed` structural signal, and relax `section_renumbered` so it no longer suppresses itself when the wording changes alongside the number.

**Architecture:** A new function, `detect_section_heading_changed`, joins the other three section-structure detectors in the existing `backend/app/section_structure.py`. `detect_section_renumbering`'s guard condition is relaxed by removing one clause. Both detectors are wired independently in `backend/app/pipeline.py`'s `compare_documents`, so a heading that changes in both dimensions produces two separate `Change` rows.

**Tech Stack:** Python 3, pytest — no new dependencies.

## Global Constraints

- New `Change.change_type` value: exactly `"section_heading_changed"` (verbatim string).
- Maps to `ai_risk_level == "Medium"` via `backend/app/risk_rules.py`'s `RISK_TABLE`.
- Fires for any matched section whose heading text differs, EXCEPT a pure number-only swap (wording identical) — that stays exclusively `section_renumbered`'s signal, unchanged.
- `detect_section_renumbering` changes behavior: it now fires whenever the leading number differs, regardless of whether the wording also changed (previously required wording to stay identical). This is a deliberate, confirmed change to already-shipped code.
- The two detectors are independent, not mutually exclusive: a heading that changes in both the number and the wording produces **two** `Change` rows — one `section_renumbered`, one `section_heading_changed` — not one row trying to describe both facts, and not one suppressing the other.
- `section` / `old_text` = old heading, `new_text` = new heading (old-heading convention, matching every other matched-section detector in this file).
- `old_page`/`new_page` = `None` always (no single paragraph to anchor to — consistent with the other three detectors).
- `source` = `"Body"` always; `confidence` = `1.0` always.
- Sections with a synthetic heading (`"Preamble"` or matching `^Paragraph \d+$`) on either side must never produce `section_heading_changed` — same guard as the other three detectors, via the existing `is_synthetic_heading` helper.
- Reference: `docs/superpowers/specs/2026-08-14-section-heading-changed-design.md`.

---

### Task 1: Relax section_renumbered, add detect_section_heading_changed

**Files:**
- Modify: `backend/app/section_structure.py`
- Modify: `backend/tests/test_section_structure.py`
- Modify: `backend/app/risk_rules.py`
- Modify: `backend/tests/test_risk_rules.py`

**Interfaces:**
- Consumes: `app.models.Change`, `app.models.Section`, `app.models.SectionMatch` (pre-existing). The existing `_split_heading_number` and `is_synthetic_heading` helpers in `app/section_structure.py` (pre-existing, same file).
- Produces: `detect_section_heading_changed(matches: list[SectionMatch], old_sections: list[Section], new_sections: list[Section]) -> list[Change]` in `app/section_structure.py`. Consumed by Task 2. `detect_section_renumbering`'s relaxed behavior is also consumed by Task 2's integration test.

- [ ] **Step 1: Relax `detect_section_renumbering`'s guard**

In `backend/app/section_structure.py`, find (verify by reading the file first — this may have drifted):

```python
        old_num, old_rest = old_split
        new_num, new_rest = new_split
        if old_num == new_num or old_rest != new_rest:
            continue
```

Replace with:

```python
        old_num, old_rest = old_split
        new_num, new_rest = new_split
        if old_num == new_num:
            continue
```

(`old_rest`/`new_rest` are still unpacked — they're consumed later by `detect_section_heading_changed`'s own logic in Step 4, not removed from this function's unpacking, just no longer part of this function's guard condition.)

- [ ] **Step 2: Update the existing test that this relaxation changes**

In `backend/tests/test_section_structure.py`, find:

```python
def test_number_and_wording_both_changing_is_not_flagged_as_pure_renumbering():
    old_sections = [Section(heading="2.0 Acceptance Criteria", paragraphs=[])]
    new_sections = [Section(heading="3.0 Acceptance Criteria for Assay", paragraphs=[])]
    matches = [SectionMatch(old_index=0, new_index=0, score=1.0)]

    assert detect_section_renumbering(matches, old_sections, new_sections) == []
```

Replace with:

```python
def test_number_and_wording_both_changing_flags_renumbering_too():
    old_sections = [Section(heading="2.0 Acceptance Criteria", paragraphs=[])]
    new_sections = [Section(heading="3.0 Acceptance Criteria for Assay", paragraphs=[])]
    matches = [SectionMatch(old_index=0, new_index=0, score=1.0)]

    changes = detect_section_renumbering(matches, old_sections, new_sections)

    assert len(changes) == 1
    assert changes[0].change_type == "section_renumbered"
    assert changes[0].reason == "Section renumbered from '2.0' to '3.0'."
```

(The test name changes because the old name asserted the opposite of the new, correct behavior — a stale name here would actively mislead the next reader.)

- [ ] **Step 3: Run the existing suite to confirm the relaxation is correctly applied**

Run (from `backend/`): `python -m pytest tests/test_section_structure.py -v`
Expected: PASS, all tests, including the renamed/rewritten test from Step 2. Every other pre-existing test in the file must still pass unchanged (none of them exercise the "wording also changed" case except this one).

- [ ] **Step 4: Write the failing tests for `detect_section_heading_changed`**

In `backend/tests/test_section_structure.py`, replace the top-of-file import block:

```python
from app.section_structure import (
    detect_section_renumbering, detect_section_reordering,
    detect_section_added, detect_section_deleted,
)
```

with:

```python
from app.section_structure import (
    detect_section_renumbering, detect_section_reordering,
    detect_section_added, detect_section_deleted, detect_section_heading_changed,
)
```

Append these test functions:

```python
def test_pure_rewording_is_detected():
    old_sections = [Section(heading="8.0 Deviation Handling", paragraphs=[])]
    new_sections = [Section(heading="8.0 Non-Conformance Management", paragraphs=[])]
    matches = [SectionMatch(old_index=0, new_index=0, score=1.0)]

    changes = detect_section_heading_changed(matches, old_sections, new_sections)

    assert len(changes) == 1
    c = changes[0]
    assert c.change_type == "section_heading_changed"
    assert c.section == "8.0 Deviation Handling"
    assert c.old_text == "8.0 Deviation Handling"
    assert c.new_text == "8.0 Non-Conformance Management"
    assert c.reason == "Section heading changed from '8.0 Deviation Handling' to '8.0 Non-Conformance Management'."
    assert c.ai_risk_level == "Medium"
    assert c.source == "Body"
    assert c.confidence == 1.0
    assert c.old_page is None
    assert c.new_page is None


def test_pure_renumber_does_not_flag_heading_changed():
    old_sections = [Section(heading="2.0 Acceptance Criteria", paragraphs=[])]
    new_sections = [Section(heading="3.0 Acceptance Criteria", paragraphs=[])]
    matches = [SectionMatch(old_index=0, new_index=0, score=1.0)]

    assert detect_section_heading_changed(matches, old_sections, new_sections) == []


def test_number_and_wording_both_changing_flags_heading_changed_too():
    old_sections = [Section(heading="2.0 Acceptance Criteria", paragraphs=[])]
    new_sections = [Section(heading="3.0 Acceptance Criteria for Assay", paragraphs=[])]
    matches = [SectionMatch(old_index=0, new_index=0, score=1.0)]

    changes = detect_section_heading_changed(matches, old_sections, new_sections)

    assert len(changes) == 1
    assert changes[0].old_text == "2.0 Acceptance Criteria"
    assert changes[0].new_text == "3.0 Acceptance Criteria for Assay"


def test_reworded_heading_with_no_leading_number_is_detected():
    old_sections = [Section(heading="SCOPE", paragraphs=[])]
    new_sections = [Section(heading="PURPOSE", paragraphs=[])]
    matches = [SectionMatch(old_index=0, new_index=0, score=1.0)]

    changes = detect_section_heading_changed(matches, old_sections, new_sections)

    assert len(changes) == 1
    assert changes[0].old_text == "SCOPE"
    assert changes[0].new_text == "PURPOSE"


def test_identical_headings_are_not_flagged():
    old_sections = [Section(heading="1.0 Scope", paragraphs=[])]
    new_sections = [Section(heading="1.0 Scope", paragraphs=[])]
    matches = [SectionMatch(old_index=0, new_index=0, score=1.0)]

    assert detect_section_heading_changed(matches, old_sections, new_sections) == []


def test_synthetic_heading_is_not_flagged_as_heading_changed():
    old_sections = [Section(heading="Paragraph 1", paragraphs=[])]
    new_sections = [Section(heading="Paragraph 2", paragraphs=[])]
    matches = [SectionMatch(old_index=0, new_index=0, score=1.0)]

    assert detect_section_heading_changed(matches, old_sections, new_sections) == []
```

- [ ] **Step 5: Run tests to verify they fail**

Run: `python -m pytest tests/test_section_structure.py -v`
Expected: the 6 new tests FAIL with `ImportError`/`AttributeError` (`detect_section_heading_changed` doesn't exist yet); every other test (from Steps 1-3) still PASSES.

- [ ] **Step 6: Add the risk_rules entry**

In `backend/app/risk_rules.py`, add `"section_heading_changed": "Medium"` to `RISK_TABLE`:

```python
RISK_TABLE = {
    "numeric_change": "High",
    "unit_change": "High",
    "process_sequence_change": "High",
    "qualitative_specification_change": "High",
    "role_responsibility_change": "Medium",
    "reference_document_change": "Medium",
    "date_change": "Medium",
    "clarification_no_meaning_change": "Low",
    "formatting_only": "Informational",
    "section_renumbered": "Informational",
    "section_reordered": "Informational",
    "section_added": "High",
    "section_deleted": "High",
    "section_heading_changed": "Medium",
}
```

In `backend/tests/test_risk_rules.py`, add:

```python
def test_section_heading_changed_is_medium_risk():
    assert assign_risk("section_heading_changed") == "Medium"
```

- [ ] **Step 7: Write the implementation**

Append to `backend/app/section_structure.py` (at the end of the file, after `detect_section_deleted` — no new imports needed, everything used here is already imported at the top of the file):

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

- [ ] **Step 8: Run tests to verify they pass**

Run: `python -m pytest tests/test_section_structure.py tests/test_risk_rules.py -v`
Expected: PASS, all tests.

- [ ] **Step 9: Commit**

```bash
git add backend/app/section_structure.py backend/tests/test_section_structure.py backend/app/risk_rules.py backend/tests/test_risk_rules.py
git commit -m "feat: detect section heading wording changes independent of renumbering"
```

---

### Task 2: Wire detect_section_heading_changed into the comparison pipeline

**Files:**
- Modify: `backend/app/pipeline.py`
- Modify: `backend/tests/test_pipeline.py`

**Interfaces:**
- Consumes: `section_structure.detect_section_heading_changed` from Task 1 (exact signature above), and Task 1's relaxed `detect_section_renumbering`.
- Produces: nothing new for later tasks — this is the last task in the plan.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_pipeline.py`:

```python
def test_pipeline_reports_both_renumbering_and_heading_change_for_one_section():
    old_paragraphs = [
        Paragraph(text="1.0 Scope"),
        Paragraph(text="This procedure applies to testing performed in the QC lab."),
        Paragraph(text="8.0 Deviation Handling"),
        Paragraph(text="Any deviation shall be documented and approved."),
    ]
    new_paragraphs = [
        Paragraph(text="1.0 Scope"),
        Paragraph(text="This procedure applies to testing performed in the QC lab."),
        Paragraph(text="9.0 Non-Conformance Management"),
        Paragraph(text="Any deviation shall be documented and approved."),
    ]

    result = pipeline.compare_documents(old_paragraphs, new_paragraphs, "SOP_v1.txt", "SOP_v2.txt")

    renumbered = [c for c in result.changes if c.change_type == "section_renumbered"]
    heading_changed = [c for c in result.changes if c.change_type == "section_heading_changed"]

    assert len(renumbered) == 1
    assert renumbered[0].section == "8.0 Deviation Handling"
    assert renumbered[0].reason == "Section renumbered from '8.0' to '9.0'."

    assert len(heading_changed) == 1
    assert heading_changed[0].section == "8.0 Deviation Handling"
    assert heading_changed[0].old_text == "8.0 Deviation Handling"
    assert heading_changed[0].new_text == "9.0 Non-Conformance Management"
    assert heading_changed[0].ai_risk_level == "Medium"


def test_pipeline_reports_only_heading_changed_when_number_is_unchanged():
    old_paragraphs = [
        Paragraph(text="1.0 Scope"),
        Paragraph(text="This procedure applies to testing performed in the QC lab."),
    ]
    new_paragraphs = [
        Paragraph(text="1.0 Purpose"),
        Paragraph(text="This procedure applies to testing performed in the QC lab."),
    ]

    result = pipeline.compare_documents(old_paragraphs, new_paragraphs, "SOP_v1.txt", "SOP_v2.txt")

    assert result.summary.total_changes == 1
    change = result.changes[0]
    assert change.change_type == "section_heading_changed"
    assert change.old_text == "1.0 Scope"
    assert change.new_text == "1.0 Purpose"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pipeline.py -v`
Expected: both new tests FAIL — `heading_changed`/the reported change will be empty since `compare_documents` doesn't call `detect_section_heading_changed` yet.

- [ ] **Step 3: Wire the detector into compare_documents**

In `backend/app/pipeline.py`, find this block (around line 48-54):

```python
    changes: list[Change] = []
    changes.extend(section_structure.detect_section_renumbering(
        match_result.matches, old_sections, new_sections
    ))
    changes.extend(section_structure.detect_section_reordering(
        match_result.matches, old_sections, new_sections
    ))
```

Replace it with:

```python
    changes: list[Change] = []
    changes.extend(section_structure.detect_section_renumbering(
        match_result.matches, old_sections, new_sections
    ))
    changes.extend(section_structure.detect_section_heading_changed(
        match_result.matches, old_sections, new_sections
    ))
    changes.extend(section_structure.detect_section_reordering(
        match_result.matches, old_sections, new_sections
    ))
```

(Only the new `detect_section_heading_changed` call is added — the rest of `compare_documents` is unchanged.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_pipeline.py -v`
Expected: PASS, including both new tests and every pre-existing test in the file — in particular `test_pipeline_detects_renumbering_and_reordering_together` (its two renumbered sections both have identical wording on both sides, so Task 1's relaxed condition doesn't change its expected output at all — confirm this stays true rather than assuming it).

- [ ] **Step 5: Run the full backend suite**

Run (from `backend/`): `python -m pytest -v`
Expected: PASS, all tests, no regressions anywhere else in the suite.

- [ ] **Step 6: Commit**

```bash
git add backend/app/pipeline.py backend/tests/test_pipeline.py
git commit -m "feat: wire section heading change detection into compare_documents"
```
