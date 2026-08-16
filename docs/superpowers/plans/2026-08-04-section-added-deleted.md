# Section Added & Deleted Detection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect a whole section being added or deleted (not matched to anything in the other document version) as its own structural signal, instead of only surfacing as scattered per-paragraph `added_paragraph`/`deleted_paragraph` rows — and make sure heading-only sections are no longer invisible to the report.

**Architecture:** Two new pure functions in the existing `backend/app/section_structure.py` — `detect_section_added` and `detect_section_deleted` — take `match_result.inserted_indices`/`deleted_indices` and the corresponding `Section` list, and build one `Change` per whole unmatched section (skipping sections with a synthetic heading, which are headingless-document artifacts, not real structural events). `pipeline.py`'s `compare_documents` calls both and stops feeding real-headed unmatched sections into the existing per-paragraph orphan/move-reconciliation path, while synthetic-headed ones keep flowing through exactly as before.

**Tech Stack:** Python 3, pytest — no new dependencies.

## Global Constraints

- New `Change.change_type` values: exactly `"section_added"` and `"section_deleted"` (verbatim strings).
- Both map to `ai_risk_level == "High"` via `backend/app/risk_rules.py`'s `RISK_TABLE`.
- Both replace the existing per-paragraph rows for that section's content — a whole unmatched section produces exactly one `Change`, not one per paragraph.
- `old_text`/`new_text`: empty string `""` on the side that doesn't exist; on the side that does, the heading followed by every one of the section's body paragraphs, each on its own line (`"\n".join([heading] + [p.text for p in section.paragraphs])`).
- `old_page`/`new_page`: the first body paragraph's `.page` if the section has body paragraphs, else `None`.
- `source`: `"Table"` if any paragraph in the section has `from_table == True`, else `"Body"`.
- `confidence == 1.0` always (rule-based, not probabilistic).
- **Sections with a synthetic heading (`"Preamble"` or matching `^Paragraph \d+$` — the fallback `sectioning.py` invents for headingless documents) must NEVER produce a `section_added`/`section_deleted` change.** They must keep flowing through the existing per-paragraph orphan/move-reconciliation path exactly as they do today. This is the single most important correctness property in this plan — getting it wrong silently reclassifies ordinary paragraph edits in headingless (`.txt`, some PDFs) documents as High-risk structural events.
- Reference: `docs/superpowers/specs/2026-08-04-section-added-deleted-design.md`.

---

### Task 1: Promote the synthetic-heading helper, add `detect_section_added`

**Files:**
- Modify: `backend/app/section_structure.py`
- Modify: `backend/tests/test_section_structure.py`
- Modify: `backend/app/risk_rules.py`
- Modify: `backend/tests/test_risk_rules.py`

**Interfaces:**
- Consumes: `app.models.Change`, `app.models.Section` (pre-existing).
- Produces:
  - `is_synthetic_heading(heading: str) -> bool` in `app/section_structure.py` — renamed from the existing private `_is_synthetic_heading` (same behavior, dropped leading underscore since `pipeline.py` needs to call it too, not just this module internally). Consumed by Task 3.
  - `detect_section_added(inserted_indices: list[int], new_sections: list[Section]) -> list[Change]` in `app/section_structure.py`. Consumed by Task 3.

- [ ] **Step 1: Rename the existing private helper**

In `backend/app/section_structure.py`, the file currently has (verify by reading the file first — this may have drifted):

```python
_SYNTHETIC_HEADING_PATTERN = re.compile(r"^Paragraph \d+$")


def _is_synthetic_heading(heading: str) -> bool:
    return heading == "Preamble" or bool(_SYNTHETIC_HEADING_PATTERN.match(heading))
```

and, inside `detect_section_reordering`:

```python
        if _is_synthetic_heading(old_heading) or _is_synthetic_heading(new_heading):
```

Rename `_is_synthetic_heading` to `is_synthetic_heading` in both places (the function definition and the one call site inside `detect_section_reordering`). Leave `_SYNTHETIC_HEADING_PATTERN` as-is (still private — only `is_synthetic_heading` itself needs to be called from outside this module).

- [ ] **Step 2: Run the existing suite to confirm the rename didn't break anything**

Run (from `backend/`): `python -m pytest tests/test_section_structure.py -v`
Expected: PASS, all existing tests (the rename is behavior-preserving).

- [ ] **Step 3: Write the failing tests for `detect_section_added`**

Add this import at the top of `backend/tests/test_section_structure.py` (replace the existing `from app.section_structure import detect_section_renumbering, detect_section_reordering` line):

```python
from app.section_structure import (
    detect_section_renumbering, detect_section_reordering, detect_section_added,
)
```

Append these test functions:

```python
def test_new_section_with_body_is_detected():
    new_sections = [
        Section(heading="1.0 Scope", paragraphs=[Paragraph(text="existing", page=1)]),
        Section(heading="5.0 Environmental Monitoring", paragraphs=[
            Paragraph(text="Environmental monitoring of the manufacturing area shall be performed weekly.", page=3),
            Paragraph(text="Settle plates shall be used at each critical location.", page=3),
        ]),
    ]

    changes = detect_section_added([1], new_sections)

    assert len(changes) == 1
    c = changes[0]
    assert c.change_type == "section_added"
    assert c.section == "5.0 Environmental Monitoring"
    assert c.old_text == ""
    assert c.new_text == (
        "5.0 Environmental Monitoring\n"
        "Environmental monitoring of the manufacturing area shall be performed weekly.\n"
        "Settle plates shall be used at each critical location."
    )
    assert c.reason == "New section added: '5.0 Environmental Monitoring'."
    assert c.ai_risk_level == "High"
    assert c.source == "Body"
    assert c.confidence == 1.0
    assert c.old_page is None
    assert c.new_page == 3


def test_heading_only_new_section_is_still_detected():
    new_sections = [Section(heading="9.0 Reserved", paragraphs=[])]

    changes = detect_section_added([0], new_sections)

    assert len(changes) == 1
    c = changes[0]
    assert c.old_text == ""
    assert c.new_text == "9.0 Reserved"
    assert c.new_page is None


def test_synthetic_heading_new_section_is_not_flagged():
    new_sections = [Section(heading="Paragraph 1", paragraphs=[Paragraph(text="body")])]

    assert detect_section_added([0], new_sections) == []


def test_table_sourced_new_section_is_labeled_table():
    new_sections = [Section(heading="4.0 Limits", paragraphs=[Paragraph(text="cell value", from_table=True)])]

    changes = detect_section_added([0], new_sections)

    assert len(changes) == 1
    assert changes[0].source == "Table"


def test_only_inserted_indices_are_flagged_among_several_sections():
    new_sections = [
        Section(heading="1.0 Scope", paragraphs=[Paragraph(text="unchanged")]),
        Section(heading="2.0 New Section", paragraphs=[Paragraph(text="added content")]),
    ]

    changes = detect_section_added([1], new_sections)

    assert len(changes) == 1
    assert changes[0].section == "2.0 New Section"
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `python -m pytest tests/test_section_structure.py -v`
Expected: the 5 new tests FAIL with `ImportError`/`AttributeError` (`detect_section_added` doesn't exist yet); every pre-existing test (including the renamed-helper ones) still PASSES.

- [ ] **Step 5: Add the risk_rules entry**

In `backend/app/risk_rules.py`, add `"section_added": "High"` to `RISK_TABLE`:

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
}
```

In `backend/tests/test_risk_rules.py`, add:

```python
def test_section_added_is_high_risk():
    assert assign_risk("section_added") == "High"
```

- [ ] **Step 6: Write the implementation**

Append to `backend/app/section_structure.py` (after `detect_section_reordering`, at the end of the file):

```python
def detect_section_added(
    inserted_indices: list[int],
    new_sections: list[Section],
) -> list[Change]:
    changes: list[Change] = []
    for idx in inserted_indices:
        section = new_sections[idx]
        if is_synthetic_heading(section.heading):
            continue
        change_type = "section_added"
        new_text = "\n".join([section.heading] + [p.text for p in section.paragraphs])
        new_page = section.paragraphs[0].page if section.paragraphs else None
        source = "Table" if any(p.from_table for p in section.paragraphs) else "Body"
        changes.append(Change(
            change_id=str(uuid.uuid4()), section=section.heading, change_type=change_type,
            old_text="", new_text=new_text, old_page=None, new_page=new_page,
            confidence=1.0, ai_risk_level=risk_rules.assign_risk(change_type),
            reason=f"New section added: '{section.heading}'.", source=source,
        ))
    return changes
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `python -m pytest tests/test_section_structure.py tests/test_risk_rules.py -v`
Expected: PASS, all tests.

- [ ] **Step 8: Commit**

```bash
git add backend/app/section_structure.py backend/tests/test_section_structure.py backend/app/risk_rules.py backend/tests/test_risk_rules.py
git commit -m "feat: detect whole-section additions, promote synthetic-heading helper"
```

---

### Task 2: Add `detect_section_deleted`

**Files:**
- Modify: `backend/app/section_structure.py`
- Modify: `backend/tests/test_section_structure.py`
- Modify: `backend/app/risk_rules.py`
- Modify: `backend/tests/test_risk_rules.py`

**Interfaces:**
- Consumes: `is_synthetic_heading` from Task 1 (same file).
- Produces: `detect_section_deleted(deleted_indices: list[int], old_sections: list[Section]) -> list[Change]` in `app/section_structure.py`. Consumed by Task 3.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/test_section_structure.py`, replace the top-of-file import block from Task 1 with:

```python
from app.section_structure import (
    detect_section_renumbering, detect_section_reordering,
    detect_section_added, detect_section_deleted,
)
```

Append these test functions:

```python
def test_deleted_section_with_body_is_detected():
    old_sections = [
        Section(heading="7.0 Storage", paragraphs=[Paragraph(text="unchanged", page=5)]),
        Section(heading="8.0 Deviation Handling", paragraphs=[
            Paragraph(text="Any deviation from this procedure shall be documented.", page=6),
        ]),
    ]

    changes = detect_section_deleted([1], old_sections)

    assert len(changes) == 1
    c = changes[0]
    assert c.change_type == "section_deleted"
    assert c.section == "8.0 Deviation Handling"
    assert c.old_text == "8.0 Deviation Handling\nAny deviation from this procedure shall be documented."
    assert c.new_text == ""
    assert c.reason == "Section deleted: '8.0 Deviation Handling'."
    assert c.ai_risk_level == "High"
    assert c.source == "Body"
    assert c.confidence == 1.0
    assert c.old_page == 6
    assert c.new_page is None


def test_heading_only_deleted_section_is_still_detected():
    old_sections = [Section(heading="9.0 Reserved", paragraphs=[])]

    changes = detect_section_deleted([0], old_sections)

    assert len(changes) == 1
    c = changes[0]
    assert c.old_text == "9.0 Reserved"
    assert c.new_text == ""
    assert c.old_page is None


def test_synthetic_heading_deleted_section_is_not_flagged():
    old_sections = [Section(heading="Paragraph 3", paragraphs=[Paragraph(text="body")])]

    assert detect_section_deleted([0], old_sections) == []


def test_table_sourced_deleted_section_is_labeled_table():
    old_sections = [Section(heading="4.0 Limits", paragraphs=[Paragraph(text="cell value", from_table=True)])]

    changes = detect_section_deleted([0], old_sections)

    assert len(changes) == 1
    assert changes[0].source == "Table"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_section_structure.py -v`
Expected: the 4 new tests FAIL with `ImportError`/`AttributeError` (`detect_section_deleted` doesn't exist yet); every Task 1 test still PASSES.

- [ ] **Step 3: Add the risk_rules entry**

In `backend/app/risk_rules.py`, add `"section_deleted": "High"` to `RISK_TABLE` (alongside `"section_added"` from Task 1):

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
}
```

In `backend/tests/test_risk_rules.py`, add:

```python
def test_section_deleted_is_high_risk():
    assert assign_risk("section_deleted") == "High"
```

- [ ] **Step 4: Write the implementation**

Append to `backend/app/section_structure.py` (after `detect_section_added`, at the end of the file; no new imports needed — everything used here is already imported at the top of the file from Task 1):

```python
def detect_section_deleted(
    deleted_indices: list[int],
    old_sections: list[Section],
) -> list[Change]:
    changes: list[Change] = []
    for idx in deleted_indices:
        section = old_sections[idx]
        if is_synthetic_heading(section.heading):
            continue
        change_type = "section_deleted"
        old_text = "\n".join([section.heading] + [p.text for p in section.paragraphs])
        old_page = section.paragraphs[0].page if section.paragraphs else None
        source = "Table" if any(p.from_table for p in section.paragraphs) else "Body"
        changes.append(Change(
            change_id=str(uuid.uuid4()), section=section.heading, change_type=change_type,
            old_text=old_text, new_text="", old_page=old_page, new_page=None,
            confidence=1.0, ai_risk_level=risk_rules.assign_risk(change_type),
            reason=f"Section deleted: '{section.heading}'.", source=source,
        ))
    return changes
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_section_structure.py tests/test_risk_rules.py -v`
Expected: PASS, all tests (Task 1's and Task 2's).

- [ ] **Step 6: Commit**

```bash
git add backend/app/section_structure.py backend/tests/test_section_structure.py backend/app/risk_rules.py backend/tests/test_risk_rules.py
git commit -m "feat: detect whole-section deletions"
```

---

### Task 3: Wire both detectors into the comparison pipeline

**Files:**
- Modify: `backend/app/pipeline.py`
- Modify: `backend/tests/test_pipeline.py`

**Interfaces:**
- Consumes: `section_structure.detect_section_added`, `section_structure.detect_section_deleted`, `section_structure.is_synthetic_heading` from Tasks 1 and 2 (exact signatures above).
- Produces: nothing new for later tasks — this is the last task in the plan.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_pipeline.py`:

```python
def test_pipeline_reports_a_new_section_as_section_added_not_scattered_paragraphs():
    old_paragraphs = [
        Paragraph(text="1.0 Scope"),
        Paragraph(text="This procedure applies to testing performed in the QC lab."),
    ]
    new_paragraphs = [
        Paragraph(text="1.0 Scope"),
        Paragraph(text="This procedure applies to testing performed in the QC lab."),
        Paragraph(text="2.0 Environmental Monitoring"),
        Paragraph(text="Environmental monitoring shall be performed weekly using settle plates."),
    ]

    result = pipeline.compare_documents(old_paragraphs, new_paragraphs, "SOP_v1.txt", "SOP_v2.txt")

    assert result.summary.total_changes == 1
    change = result.changes[0]
    assert change.change_type == "section_added"
    assert change.section == "2.0 Environmental Monitoring"
    assert change.new_text == (
        "2.0 Environmental Monitoring\n"
        "Environmental monitoring shall be performed weekly using settle plates."
    )
    assert change.ai_risk_level == "High"


def test_pipeline_reports_a_deleted_section_as_section_deleted_not_scattered_paragraphs():
    old_paragraphs = [
        Paragraph(text="1.0 Scope"),
        Paragraph(text="This procedure applies to testing performed in the QC lab."),
        Paragraph(text="8.0 Deviation Handling"),
        Paragraph(text="Any deviation from this procedure shall be documented and approved."),
    ]
    new_paragraphs = [
        Paragraph(text="1.0 Scope"),
        Paragraph(text="This procedure applies to testing performed in the QC lab."),
    ]

    result = pipeline.compare_documents(old_paragraphs, new_paragraphs, "SOP_v1.txt", "SOP_v2.txt")

    assert result.summary.total_changes == 1
    change = result.changes[0]
    assert change.change_type == "section_deleted"
    assert change.section == "8.0 Deviation Handling"
    assert change.old_text == (
        "8.0 Deviation Handling\n"
        "Any deviation from this procedure shall be documented and approved."
    )
    assert change.ai_risk_level == "High"


def test_pipeline_headingless_paragraph_addition_still_uses_added_paragraph():
    # Regression guard: sectioning.py wraps a headingless document's paragraphs in
    # synthetic "Paragraph N" sections. Without the synthetic-heading guard, this
    # would get misreported as a High-risk section_added instead of the existing
    # Medium-risk added_paragraph. This mirrors the pre-existing
    # test_body_paragraph_addition_keeps_generic_change_type case but asserts the
    # change_type explicitly against this plan's new code path.
    old_paragraphs = []
    new_paragraphs = [Paragraph(text="New body sentence with no heading anywhere.")]

    result = pipeline.compare_documents(old_paragraphs, new_paragraphs, "old.txt", "new.txt")

    assert result.summary.total_changes == 1
    change = result.changes[0]
    assert change.change_type == "added_paragraph"
    assert change.ai_risk_level != "High"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_pipeline.py -v`
Expected: the first two new tests FAIL (no `section_added`/`section_deleted` in output yet — `compare_documents` doesn't call the new detectors, so these sections still show up as `added_paragraph`/`deleted_paragraph` and `total_changes` won't match). The third new test currently PASSES already (it's asserting today's existing behavior) — that's fine, it's here as a named regression guard for the next step, not to prove a fix.

- [ ] **Step 3: Wire the detectors into compare_documents**

In `backend/app/pipeline.py`, find this block (around line 48-56):

```python
    changes: list[Change] = []
    changes.extend(section_structure.detect_section_renumbering(
        match_result.matches, old_sections, new_sections
    ))
    changes.extend(section_structure.detect_section_reordering(
        match_result.matches, old_sections, new_sections
    ))
    orphan_deletes: list[Orphan] = []
    orphan_inserts: list[Orphan] = []
```

Replace it with:

```python
    changes: list[Change] = []
    changes.extend(section_structure.detect_section_renumbering(
        match_result.matches, old_sections, new_sections
    ))
    changes.extend(section_structure.detect_section_reordering(
        match_result.matches, old_sections, new_sections
    ))
    changes.extend(section_structure.detect_section_added(
        match_result.inserted_indices, new_sections
    ))
    changes.extend(section_structure.detect_section_deleted(
        match_result.deleted_indices, old_sections
    ))
    orphan_deletes: list[Orphan] = []
    orphan_inserts: list[Orphan] = []
```

Then find this block (around line 82-87):

```python
    for idx in match_result.deleted_indices:
        sec = old_sections[idx]
        orphan_deletes += [(p, sec.heading) for p in sec.paragraphs]
    for idx in match_result.inserted_indices:
        sec = new_sections[idx]
        orphan_inserts += [(p, sec.heading) for p in sec.paragraphs]
```

Replace it with:

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

(Only the `if section_structure.is_synthetic_heading(...)` guards are new — real-headed unmatched sections are now handled exclusively by `detect_section_added`/`detect_section_deleted` above, so they must stop flowing into the orphan lists; synthetic-headed ones keep flowing through exactly as before.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_pipeline.py -v`
Expected: PASS, including all 3 new tests and every pre-existing test in the file — in particular `test_body_paragraph_addition_keeps_generic_change_type`, `test_table_cell_deletion_gets_table_labeled_change_type`, and `test_table_cell_addition_gets_table_labeled_change_type` (all three exercise a single headingless/synthetic section going through `inserted_indices`/`deleted_indices`, and must keep producing their original `added_paragraph`/`deleted_table_content`/`added_table_content` results unchanged — this is the concrete proof that the synthetic-heading guard works, not just the new dedicated regression test from Step 1).

- [ ] **Step 5: Run the full backend suite**

Run (from `backend/`): `python -m pytest -v`
Expected: PASS, all tests, no regressions anywhere else in the suite.

- [ ] **Step 6: Commit**

```bash
git add backend/app/pipeline.py backend/tests/test_pipeline.py
git commit -m "feat: wire whole-section added/deleted detection into compare_documents"
```
