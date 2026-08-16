# Section Reordering & Renumbering Detection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect and surface two structural signals that fall through the existing pipeline today: a matched section's heading number changing (renumbering), and a matched section's position changing relative to its siblings (reordering).

**Architecture:** A new module, `backend/app/section_structure.py`, adds two pure functions that operate on `section_matching.py`'s already-computed `SectionMatch` list plus the old/new `Section` lists: `detect_section_renumbering` (regex-based heading-number comparison) and `detect_section_reordering` (longest-increasing-subsequence comparison of matched positions, so insertions/deletions elsewhere never produce false positives). `pipeline.py`'s `compare_documents` calls both immediately after `section_matching.match_sections(...)` and extends its `changes` list with the results.

**Tech Stack:** Python 3, pytest — no new dependencies.

## Global Constraints

- New `Change.change_type` values: exactly `"section_renumbered"` and `"section_reordered"` (verbatim strings).
- Both new types map to `ai_risk_level == "Informational"` via `backend/app/risk_rules.py`'s `RISK_TABLE`.
- Both new types always produce `Change.source == "Body"` (never `"Table"` — they're derived from `Section.heading`, never table content) and `Change.confidence == 1.0` (rule-based, not probabilistic).
- Both new types always produce `Change.old_page == None` and `Change.new_page == None` — a section-level structural signal doesn't map to one paragraph's page, and `Section` doesn't carry a page for its heading.
- Renumbering fires ONLY when a matched section's heading number prefix changes AND the rest of the heading text (after the number) is identical after whitespace-collapsing. Any other heading wording change (reworded, or renumbered+reworded together) must NOT fire `section_renumbered`.
- Reordering fires ONLY for matches excluded from the longest increasing subsequence of `new_index` values (sorted by `old_index`) — never a raw `old_index != new_index` check, which would false-positive on every section after an insertion/deletion.
- Reference: `docs/superpowers/specs/2026-08-03-section-reordering-renumbering-design.md`.

---

### Task 1: Section renumbering detector

**Files:**
- Create: `backend/app/section_structure.py`
- Create: `backend/tests/test_section_structure.py`
- Modify: `backend/app/risk_rules.py`
- Modify: `backend/tests/test_risk_rules.py`

**Interfaces:**
- Consumes: `app.models.Change`, `app.models.Section`, `app.models.SectionMatch` (all pre-existing — see `backend/app/models.py`). `SectionMatch` has fields `old_index: int`, `new_index: int`, `score: float`. `Section` has fields `heading: str`, `paragraphs: list[Paragraph]`.
- Produces: `detect_section_renumbering(matches: list[SectionMatch], old_sections: list[Section], new_sections: list[Section]) -> list[Change]` in `app/section_structure.py`. Consumed by Task 3.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_section_structure.py`:

```python
from app.models import Section, Paragraph, SectionMatch
from app.section_structure import detect_section_renumbering


def test_pure_renumber_is_detected():
    old_sections = [Section(heading="2.0 Acceptance Criteria", paragraphs=[Paragraph(text="body")])]
    new_sections = [Section(heading="3.0 Acceptance Criteria", paragraphs=[Paragraph(text="body")])]
    matches = [SectionMatch(old_index=0, new_index=0, score=1.0)]

    changes = detect_section_renumbering(matches, old_sections, new_sections)

    assert len(changes) == 1
    c = changes[0]
    assert c.change_type == "section_renumbered"
    assert c.section == "3.0 Acceptance Criteria"
    assert c.old_text == "2.0 Acceptance Criteria"
    assert c.new_text == "3.0 Acceptance Criteria"
    assert c.reason == "Section renumbered from '2.0' to '3.0'."
    assert c.ai_risk_level == "Informational"
    assert c.source == "Body"
    assert c.confidence == 1.0
    assert c.old_page is None
    assert c.new_page is None


def test_unchanged_number_is_not_flagged():
    old_sections = [Section(heading="1.0 Scope", paragraphs=[])]
    new_sections = [Section(heading="1.0 Scope", paragraphs=[])]
    matches = [SectionMatch(old_index=0, new_index=0, score=1.0)]

    assert detect_section_renumbering(matches, old_sections, new_sections) == []


def test_reworded_heading_with_same_number_is_not_flagged():
    old_sections = [Section(heading="2.0 Acceptance Criteria", paragraphs=[])]
    new_sections = [Section(heading="2.0 Acceptance Criteria for Assay", paragraphs=[])]
    matches = [SectionMatch(old_index=0, new_index=0, score=1.0)]

    assert detect_section_renumbering(matches, old_sections, new_sections) == []


def test_number_and_wording_both_changing_is_not_flagged_as_pure_renumbering():
    old_sections = [Section(heading="2.0 Acceptance Criteria", paragraphs=[])]
    new_sections = [Section(heading="3.0 Acceptance Criteria for Assay", paragraphs=[])]
    matches = [SectionMatch(old_index=0, new_index=0, score=1.0)]

    assert detect_section_renumbering(matches, old_sections, new_sections) == []


def test_headings_without_a_leading_number_are_not_flagged():
    old_sections = [Section(heading="SCOPE", paragraphs=[])]
    new_sections = [Section(heading="PURPOSE", paragraphs=[])]
    matches = [SectionMatch(old_index=0, new_index=0, score=1.0)]

    assert detect_section_renumbering(matches, old_sections, new_sections) == []


def test_only_the_side_with_a_leading_number_removed_is_not_flagged():
    old_sections = [Section(heading="2.0 Acceptance Criteria", paragraphs=[])]
    new_sections = [Section(heading="Acceptance Criteria", paragraphs=[])]
    matches = [SectionMatch(old_index=0, new_index=0, score=1.0)]

    assert detect_section_renumbering(matches, old_sections, new_sections) == []


def test_only_renumbered_matches_are_flagged_among_several():
    old_sections = [
        Section(heading="1.0 Scope", paragraphs=[]),
        Section(heading="2.0 Acceptance Criteria", paragraphs=[]),
    ]
    new_sections = [
        Section(heading="1.0 Scope", paragraphs=[]),
        Section(heading="3.0 Acceptance Criteria", paragraphs=[]),
    ]
    matches = [
        SectionMatch(old_index=0, new_index=0, score=1.0),
        SectionMatch(old_index=1, new_index=1, score=1.0),
    ]

    changes = detect_section_renumbering(matches, old_sections, new_sections)

    assert len(changes) == 1
    assert changes[0].old_text == "2.0 Acceptance Criteria"
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `backend/`): `python -m pytest tests/test_section_structure.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.section_structure'` (or import error) for every test.

- [ ] **Step 3: Add the risk_rules entry**

In `backend/app/risk_rules.py`, add `"section_renumbered": "Informational"` to `RISK_TABLE`:

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
}
```

In `backend/tests/test_risk_rules.py`, add a new test function (leave every existing test untouched):

```python
def test_section_renumbered_is_informational_risk():
    assert assign_risk("section_renumbered") == "Informational"
```

- [ ] **Step 4: Write the implementation**

Create `backend/app/section_structure.py`:

```python
import re
import uuid

from app import risk_rules
from app.models import Change, Section, SectionMatch

_HEADING_NUMBER_PATTERN = re.compile(r"^(?P<num>\d+(?:\.\d+)*)\s+(?P<rest>.*)$")


def _split_heading_number(heading: str) -> tuple[str, str] | None:
    match = _HEADING_NUMBER_PATTERN.match(heading)
    if not match:
        return None
    return match.group("num"), " ".join(match.group("rest").split())


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
        if old_num == new_num or old_rest != new_rest:
            continue
        change_type = "section_renumbered"
        changes.append(Change(
            change_id=str(uuid.uuid4()), section=new_heading, change_type=change_type,
            old_text=old_heading, new_text=new_heading, old_page=None, new_page=None,
            confidence=1.0, ai_risk_level=risk_rules.assign_risk(change_type),
            reason=f"Section renumbered from '{old_num}' to '{new_num}'.", source="Body",
        ))
    return changes
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_section_structure.py tests/test_risk_rules.py -v`
Expected: PASS, all tests.

- [ ] **Step 6: Commit**

```bash
git add backend/app/section_structure.py backend/tests/test_section_structure.py backend/app/risk_rules.py backend/tests/test_risk_rules.py
git commit -m "feat: detect section renumbering (heading number change, wording unchanged)"
```

---

### Task 2: Section reordering detector

**Files:**
- Modify: `backend/app/section_structure.py`
- Modify: `backend/tests/test_section_structure.py`
- Modify: `backend/app/risk_rules.py`
- Modify: `backend/tests/test_risk_rules.py`

**Interfaces:**
- Consumes: same `Change`/`Section`/`SectionMatch` types as Task 1; `detect_section_renumbering` from Task 1 is not called by this task's code, but both live in the same file.
- Produces: `detect_section_reordering(matches: list[SectionMatch], old_sections: list[Section], new_sections: list[Section]) -> list[Change]` in `app/section_structure.py`. Consumed by Task 3.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/test_section_structure.py`, replace the existing top-of-file import line (`from app.section_structure import detect_section_renumbering`) with:

```python
from app.section_structure import detect_section_renumbering, detect_section_reordering
```

Then append these test functions:

```python
def test_empty_matches_returns_no_changes():
    assert detect_section_reordering([], [], []) == []


def test_matches_with_unchanged_relative_order_produce_no_changes():
    sections = [Section(heading=f"{n}", paragraphs=[]) for n in ["A", "B", "C"]]
    matches = [
        SectionMatch(old_index=0, new_index=0, score=1.0),
        SectionMatch(old_index=1, new_index=1, score=1.0),
        SectionMatch(old_index=2, new_index=2, score=1.0),
    ]

    assert detect_section_reordering(matches, sections, sections) == []


def test_insertion_elsewhere_does_not_cause_a_false_positive():
    # Old: A, B, C. New: X, A, B, C (X inserted at the front, unmatched).
    # Every matched section's raw index shifts by +1, but their relative
    # order to each other is unchanged, so nothing should be flagged.
    old_sections = [Section(heading=n, paragraphs=[]) for n in ["A", "B", "C"]]
    new_sections = [Section(heading=n, paragraphs=[]) for n in ["X", "A", "B", "C"]]
    matches = [
        SectionMatch(old_index=0, new_index=1, score=1.0),
        SectionMatch(old_index=1, new_index=2, score=1.0),
        SectionMatch(old_index=2, new_index=3, score=1.0),
    ]

    assert detect_section_reordering(matches, old_sections, new_sections) == []


def test_section_that_jumps_ahead_of_others_is_flagged():
    # Old: A, B, C, D. New: D, A, B, C (D jumps to the front; A, B, C keep
    # their relative order to each other, so only D should be flagged).
    old_sections = [Section(heading=n, paragraphs=[]) for n in ["A", "B", "C", "D"]]
    new_sections = [Section(heading=n, paragraphs=[]) for n in ["D", "A", "B", "C"]]
    matches = [
        SectionMatch(old_index=0, new_index=1, score=1.0),  # A
        SectionMatch(old_index=1, new_index=2, score=1.0),  # B
        SectionMatch(old_index=2, new_index=3, score=1.0),  # C
        SectionMatch(old_index=3, new_index=0, score=1.0),  # D
    ]

    changes = detect_section_reordering(matches, old_sections, new_sections)

    assert len(changes) == 1
    c = changes[0]
    assert c.change_type == "section_reordered"
    assert c.section == "D"
    assert c.old_text == "D"
    assert c.new_text == "D"
    assert c.reason == "Section moved from position 4 to position 1 in the document."
    assert c.ai_risk_level == "Informational"
    assert c.source == "Body"
    assert c.confidence == 1.0
    assert c.old_page is None
    assert c.new_page is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_section_structure.py -v`
Expected: the 4 new tests FAIL with `ImportError`/`AttributeError` (`detect_section_reordering` doesn't exist yet); the Task 1 tests still PASS.

- [ ] **Step 3: Add the risk_rules entry**

In `backend/app/risk_rules.py`, add `"section_reordered": "Informational"` to `RISK_TABLE` (alongside the `"section_renumbered"` entry from Task 1):

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
}
```

In `backend/tests/test_risk_rules.py`, add:

```python
def test_section_reordered_is_informational_risk():
    assert assign_risk("section_reordered") == "Informational"
```

- [ ] **Step 4: Write the implementation**

Append to `backend/app/section_structure.py` (the `import re`/`import uuid`/`from app import risk_rules`/`from app.models import Change, Section, SectionMatch` lines already at the top of the file from Task 1 cover everything needed — no new imports):

```python
def _longest_increasing_subsequence_indices(values: list[int]) -> set[int]:
    if not values:
        return set()

    n = len(values)
    lengths = [1] * n
    predecessors = [-1] * n

    for i in range(n):
        for j in range(i):
            if values[j] < values[i] and lengths[j] + 1 > lengths[i]:
                lengths[i] = lengths[j] + 1
                predecessors[i] = j

    best_end = max(range(n), key=lambda i: lengths[i])
    kept = set()
    i = best_end
    while i != -1:
        kept.add(i)
        i = predecessors[i]
    return kept


def detect_section_reordering(
    matches: list[SectionMatch],
    old_sections: list[Section],
    new_sections: list[Section],
) -> list[Change]:
    if not matches:
        return []

    ordered = sorted(matches, key=lambda m: m.old_index)
    new_index_sequence = [m.new_index for m in ordered]
    kept_positions = _longest_increasing_subsequence_indices(new_index_sequence)

    changes: list[Change] = []
    for i, m in enumerate(ordered):
        if i in kept_positions:
            continue
        heading = new_sections[m.new_index].heading
        change_type = "section_reordered"
        reason = (
            f"Section moved from position {m.old_index + 1} to "
            f"position {m.new_index + 1} in the document."
        )
        changes.append(Change(
            change_id=str(uuid.uuid4()), section=heading, change_type=change_type,
            old_text=heading, new_text=heading, old_page=None, new_page=None,
            confidence=1.0, ai_risk_level=risk_rules.assign_risk(change_type),
            reason=reason, source="Body",
        ))
    return changes
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_section_structure.py tests/test_risk_rules.py -v`
Expected: PASS, all tests (Task 1's and Task 2's).

- [ ] **Step 6: Commit**

```bash
git add backend/app/section_structure.py backend/tests/test_section_structure.py backend/app/risk_rules.py backend/tests/test_risk_rules.py
git commit -m "feat: detect section reordering via longest-increasing-subsequence"
```

---

### Task 3: Wire detectors into the comparison pipeline

**Files:**
- Modify: `backend/app/pipeline.py`
- Modify: `backend/tests/test_pipeline.py`

**Interfaces:**
- Consumes: `section_structure.detect_section_renumbering` and `section_structure.detect_section_reordering` from Tasks 1 and 2 (exact signatures above).
- Produces: nothing new for later tasks — this is the last task in the plan.

- [ ] **Step 1: Write the failing test**

This integration test's expected output was verified directly against the real embedding model before writing this plan (not assumed) — running `section_matching.match_sections` on this exact old/new paragraph pair produces matches `[(old=0,new=0,score=1.0), (old=1,new=2,score=0.911), (old=2,new=1,score=0.870)]`, confirmed by direct execution.

Append to `backend/tests/test_pipeline.py`:

```python
def test_pipeline_detects_renumbering_and_reordering_together():
    old_paragraphs = [
        Paragraph(text="1.0 Scope"),
        Paragraph(text="This procedure applies to testing performed in the QC lab."),
        Paragraph(text="2.0 Acceptance Criteria"),
        Paragraph(text="Results shall conform to the specified limits."),
        Paragraph(text="3.0 Approval"),
        Paragraph(text="The Quality Assurance Manager shall approve results."),
    ]
    new_paragraphs = [
        Paragraph(text="1.0 Scope"),
        Paragraph(text="This procedure applies to testing performed in the QC lab."),
        Paragraph(text="2.0 Approval"),
        Paragraph(text="The Quality Assurance Manager shall approve results."),
        Paragraph(text="3.0 Acceptance Criteria"),
        Paragraph(text="Results shall conform to the specified limits."),
    ]

    result = pipeline.compare_documents(old_paragraphs, new_paragraphs, "SOP_v1.txt", "SOP_v2.txt")

    renumbered = {c.old_text: c for c in result.changes if c.change_type == "section_renumbered"}
    reordered = [c for c in result.changes if c.change_type == "section_reordered"]

    assert set(renumbered.keys()) == {"2.0 Acceptance Criteria", "3.0 Approval"}
    assert renumbered["2.0 Acceptance Criteria"].new_text == "3.0 Acceptance Criteria"
    assert renumbered["2.0 Acceptance Criteria"].reason == "Section renumbered from '2.0' to '3.0'."
    assert renumbered["3.0 Approval"].new_text == "2.0 Approval"
    assert renumbered["3.0 Approval"].reason == "Section renumbered from '3.0' to '2.0'."
    for c in renumbered.values():
        assert c.ai_risk_level == "Informational"
        assert c.source == "Body"

    assert len(reordered) == 1
    assert reordered[0].section == "2.0 Approval"
    assert reordered[0].reason == "Section moved from position 3 to position 2 in the document."
    assert reordered[0].ai_risk_level == "Informational"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pipeline.py::test_pipeline_detects_renumbering_and_reordering_together -v`
Expected: FAIL — `renumbered`/`reordered` will be empty since `compare_documents` doesn't call the new detectors yet, so the `set(...) == {...}` and `len(reordered) == 1` assertions fail.

- [ ] **Step 3: Wire the detectors into compare_documents**

In `backend/app/pipeline.py`, replace the existing first import line (`from app import sectioning, section_matching, paragraph_diff, move_reconciliation`) with:

```python
from app import sectioning, section_matching, section_structure, paragraph_diff, move_reconciliation
```

Then, in `compare_documents` (around line 46-50), find this exact block:

```python
    match_result = section_matching.match_sections(old_sections, new_sections)

    changes: list[Change] = []
    orphan_deletes: list[Orphan] = []
    orphan_inserts: list[Orphan] = []
```

Replace it with:

```python
    match_result = section_matching.match_sections(old_sections, new_sections)

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

(Only the two `changes.extend(...)` calls are new — everything else in `compare_documents` is unchanged.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_pipeline.py -v`
Expected: PASS, including `test_pipeline_detects_renumbering_and_reordering_together` and every pre-existing test in the file (in particular `test_pipeline_reproduces_the_outline_example`, which has no numbered headings, so `detect_section_renumbering`/`detect_section_reordering` must produce zero changes for it — confirming the new calls don't perturb documents with no structural drift).

- [ ] **Step 5: Run the full backend suite**

Run (from `backend/`): `python -m pytest -v`
Expected: PASS, all tests, no regressions anywhere else in the suite.

- [ ] **Step 6: Commit**

```bash
git add backend/app/pipeline.py backend/tests/test_pipeline.py
git commit -m "feat: wire section renumbering/reordering detection into compare_documents"
```
