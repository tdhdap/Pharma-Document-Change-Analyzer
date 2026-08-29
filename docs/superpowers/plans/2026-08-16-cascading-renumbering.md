# Cascading vs Deliberate Renumbering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Distinguish a section number that shifted only because a section was added or deleted above it from one that someone deliberately renumbered, so a single insertion stops burying the report under dozens of mechanical rows.

**Architecture:** `detect_section_renumbering` gains the inserted/deleted section indices and computes the shift each section's number *should* have if nothing deliberate happened — numbered sections inserted above it minus numbered sections deleted above it. When the actual top-level shift matches that arithmetic exactly, the change is emitted as `section_renumbered_cascade` instead of `section_renumbered`. Anything the arithmetic does not explain exactly stays a deliberate renumbering, so the rule over-reports rather than hides.

**Tech Stack:** Python, FastAPI backend, pytest.

## Global Constraints

- `expected_shift = (numbered sections inserted above it) - (numbered sections deleted above it)`. "Above it" means: inserted sections whose index in the NEW document is less than this section's `new_index`; deleted sections whose index in the OLD document is less than its `old_index`. (spec: "The rule")
- Only sections whose heading parses as numbered count toward the arithmetic — pseudo-sections (`Page Header`, `Text Box 1`, `Footnote 1`, `Preamble`) carry no number and must not affect it. Use `_split_heading_number(...) is not None` as the test. (spec: "The rule")
- Classify as cascading only when `expected_shift != 0` **and** the actual shift equals it exactly. Everything else stays `section_renumbered`. (spec: "The rule")
- Compare only the **first** dot-separated component of the number. This is what keeps sub-numbering shifts like `3.1` → `3.2` classified as deliberate. (spec: "Design per component")
- A number component that fails to parse as an integer means the arithmetic cannot be trusted — the change stays `section_renumbered`. (spec: "Design per component")
- The new type is exactly `"section_renumbered_cascade"`, at risk `"Informational"` — matching `section_renumbered`, not the `DEFAULT_RISK` of `"Medium"`. (spec: "Decision", "backend/app/risk_rules.py")
- The two new parameters default to `None` so existing three-argument callers keep working and every renumbering reports as `section_renumbered`. (spec: "Design per component")
- Do not change `detect_section_reordering`, `detect_section_added`, `detect_section_deleted`, `detect_section_heading_changed`, or the risk of any existing change type. (spec: "Unaffected", "Out of Scope")

---

### Task 1: Classify cascading renumbering

**Files:**
- Modify: `backend/app/section_structure.py` (`detect_section_renumbering`)
- Modify: `backend/app/risk_rules.py` (one new `RISK_TABLE` entry)
- Modify: `backend/app/pipeline.py` (pass two already-available arguments at the single call site)
- Test: `backend/tests/test_section_structure.py`
- Test: `backend/tests/test_risk_rules.py`
- Test: `backend/tests/test_pipeline.py`

**Interfaces:**
- Produces: `detect_section_renumbering(matches, old_sections, new_sections, inserted_indices=None, deleted_indices=None) -> list[Change]`. The two new parameters are `list[int] | None`. Emits `change_type` of either `"section_renumbered"` (unchanged) or the new `"section_renumbered_cascade"`.
- Consumes: `SectionMatchResult.inserted_indices` and `.deleted_indices`, which already exist (`backend/app/models.py:37-40`) and are already produced by `section_matching.match_sections`. No new plumbing is needed to obtain them.
- Consumes: `_split_heading_number(heading) -> tuple[str, str] | None`, already defined at the top of `backend/app/section_structure.py`. Returns `None` for headings with no leading number, which is exactly the pseudo-section test the arithmetic needs.

All seven existing calls to `detect_section_renumbering` in `backend/tests/test_section_structure.py` pass three arguments. With the new parameters defaulting to `None`, `expected_shift` is always `0` for them, so every one keeps reporting `section_renumbered` and none need editing. This was verified by applying the change and running the full suite before this plan was written.

- [ ] **Step 1: Write the failing test for the risk entry**

Append to `backend/tests/test_risk_rules.py`:

```python
def test_section_renumbered_cascade_is_informational_risk():
    # Must match section_renumbered rather than falling through to the
    # DEFAULT_RISK of "Medium", which would silently promote a cascade above
    # the renumbering it replaces.
    assert assign_risk("section_renumbered_cascade") == "Informational"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && python -m pytest tests/test_risk_rules.py -k cascade -v`
Expected: FAIL — `assert 'Medium' == 'Informational'`, because the unknown type currently falls through to `DEFAULT_RISK`.

- [ ] **Step 3: Add the risk entry**

In `backend/app/risk_rules.py`, find:

```python
    "section_renumbered": "Informational",
```

Replace with:

```python
    "section_renumbered": "Informational",
    "section_renumbered_cascade": "Informational",
```

- [ ] **Step 4: Run it to verify it passes**

Run: `cd backend && python -m pytest tests/test_risk_rules.py -v`
Expected: all pass, including the new test and the pre-existing `test_structural_and_unknown_types_default_to_medium` (which enumerates specific types and does not include the new one).

- [ ] **Step 5: Write the failing tests for the classification rule**

Append to `backend/tests/test_section_structure.py`:

```python
def test_renumbering_caused_by_an_insertion_above_is_cascading():
    old_sections = [
        Section(heading="1.0 Purpose", paragraphs=[]),
        Section(heading="2.0 Equipment", paragraphs=[]),
        Section(heading="3.0 Records", paragraphs=[]),
    ]
    new_sections = [
        Section(heading="1.0 Purpose", paragraphs=[]),
        Section(heading="2.0 Safety", paragraphs=[]),
        Section(heading="3.0 Equipment", paragraphs=[]),
        Section(heading="4.0 Records", paragraphs=[]),
    ]
    matches = [
        SectionMatch(old_index=0, new_index=0, score=1.0),
        SectionMatch(old_index=1, new_index=2, score=1.0),
        SectionMatch(old_index=2, new_index=3, score=1.0),
    ]

    changes = detect_section_renumbering(
        matches, old_sections, new_sections, inserted_indices=[1], deleted_indices=[]
    )

    assert [c.change_type for c in changes] == [
        "section_renumbered_cascade", "section_renumbered_cascade",
    ]
    assert changes[0].reason == (
        "Section renumbered from '2.0' to '3.0' as a side effect of "
        "1 section added above it; wording unchanged."
    )
    assert changes[0].ai_risk_level == "Informational"


def test_renumbering_caused_by_a_deletion_above_is_cascading():
    old_sections = [
        Section(heading="1.0 Purpose", paragraphs=[]),
        Section(heading="2.0 Scope", paragraphs=[]),
        Section(heading="3.0 Equipment", paragraphs=[]),
    ]
    new_sections = [
        Section(heading="1.0 Purpose", paragraphs=[]),
        Section(heading="2.0 Equipment", paragraphs=[]),
    ]
    matches = [
        SectionMatch(old_index=0, new_index=0, score=1.0),
        SectionMatch(old_index=2, new_index=1, score=1.0),
    ]

    changes = detect_section_renumbering(
        matches, old_sections, new_sections, inserted_indices=[], deleted_indices=[1]
    )

    assert [c.change_type for c in changes] == ["section_renumbered_cascade"]
    assert changes[0].reason == (
        "Section renumbered from '3.0' to '2.0' as a side effect of "
        "1 section removed above it; wording unchanged."
    )


def test_two_insertions_above_produce_a_plural_reason():
    old_sections = [
        Section(heading="1.0 Purpose", paragraphs=[]),
        Section(heading="2.0 Records", paragraphs=[]),
    ]
    new_sections = [
        Section(heading="1.0 Purpose", paragraphs=[]),
        Section(heading="2.0 Safety", paragraphs=[]),
        Section(heading="3.0 Training", paragraphs=[]),
        Section(heading="4.0 Records", paragraphs=[]),
    ]
    matches = [
        SectionMatch(old_index=0, new_index=0, score=1.0),
        SectionMatch(old_index=1, new_index=3, score=1.0),
    ]

    changes = detect_section_renumbering(
        matches, old_sections, new_sections, inserted_indices=[1, 2], deleted_indices=[]
    )

    assert changes[0].change_type == "section_renumbered_cascade"
    assert changes[0].reason == (
        "Section renumbered from '2.0' to '4.0' as a side effect of "
        "2 sections added above it; wording unchanged."
    )


def test_swap_with_no_insertion_or_deletion_stays_deliberate():
    # Two sections trading places renumbers both, but nothing was added or
    # removed, so expected_shift is 0 and neither qualifies as cascading.
    # detect_section_reordering reports the swap itself separately.
    old_sections = [
        Section(heading="1.0 Purpose", paragraphs=[]),
        Section(heading="2.0 Equipment", paragraphs=[]),
        Section(heading="3.0 Records", paragraphs=[]),
    ]
    new_sections = [
        Section(heading="1.0 Purpose", paragraphs=[]),
        Section(heading="2.0 Records", paragraphs=[]),
        Section(heading="3.0 Equipment", paragraphs=[]),
    ]
    matches = [
        SectionMatch(old_index=0, new_index=0, score=1.0),
        SectionMatch(old_index=1, new_index=2, score=1.0),
        SectionMatch(old_index=2, new_index=1, score=1.0),
    ]

    changes = detect_section_renumbering(
        matches, old_sections, new_sections, inserted_indices=[], deleted_indices=[]
    )

    assert [c.change_type for c in changes] == [
        "section_renumbered", "section_renumbered",
    ]


def test_deliberate_renumber_alongside_an_insertion_stays_deliberate():
    # A section was inserted above (expected_shift = 1), but this section's
    # number jumped by 2 - the arithmetic does not explain it, so it is
    # deliberate.
    old_sections = [
        Section(heading="1.0 Purpose", paragraphs=[]),
        Section(heading="2.0 Records", paragraphs=[]),
    ]
    new_sections = [
        Section(heading="1.0 Purpose", paragraphs=[]),
        Section(heading="2.0 Safety", paragraphs=[]),
        Section(heading="4.0 Records", paragraphs=[]),
    ]
    matches = [
        SectionMatch(old_index=0, new_index=0, score=1.0),
        SectionMatch(old_index=1, new_index=2, score=1.0),
    ]

    changes = detect_section_renumbering(
        matches, old_sections, new_sections, inserted_indices=[1], deleted_indices=[]
    )

    assert [c.change_type for c in changes] == ["section_renumbered"]


def test_gapped_numbering_still_classifies_as_cascading():
    # The document numbers 1.0, 2.0, 4.0 - there is no 3.0. A position-based
    # rule would misjudge this; the arithmetic compares against what actually
    # changed structurally, so it holds.
    old_sections = [
        Section(heading="1.0 Purpose", paragraphs=[]),
        Section(heading="2.0 Scope", paragraphs=[]),
        Section(heading="4.0 Equipment", paragraphs=[]),
    ]
    new_sections = [
        Section(heading="1.0 Purpose", paragraphs=[]),
        Section(heading="2.0 Scope", paragraphs=[]),
        Section(heading="3.0 Safety", paragraphs=[]),
        Section(heading="5.0 Equipment", paragraphs=[]),
    ]
    matches = [
        SectionMatch(old_index=0, new_index=0, score=1.0),
        SectionMatch(old_index=1, new_index=1, score=1.0),
        SectionMatch(old_index=2, new_index=3, score=1.0),
    ]

    changes = detect_section_renumbering(
        matches, old_sections, new_sections, inserted_indices=[2], deleted_indices=[]
    )

    assert [c.change_type for c in changes] == ["section_renumbered_cascade"]


def test_sub_numbering_shift_stays_deliberate():
    # Only the first dot-separated component participates in the comparison,
    # so a shift at a deeper level is not explained by the arithmetic and
    # stays deliberate - the conservative direction.
    old_sections = [
        Section(heading="3.1 Equipment", paragraphs=[]),
    ]
    new_sections = [
        Section(heading="3.0 Safety", paragraphs=[]),
        Section(heading="3.2 Equipment", paragraphs=[]),
    ]
    matches = [SectionMatch(old_index=0, new_index=1, score=1.0)]

    changes = detect_section_renumbering(
        matches, old_sections, new_sections, inserted_indices=[0], deleted_indices=[]
    )

    assert [c.change_type for c in changes] == ["section_renumbered"]


def test_unnumbered_pseudo_sections_do_not_count_toward_the_shift():
    # "Page Header" is a pseudo-section this tool generates; it carries no
    # number, so inserting one above a numbered section must not make a
    # genuine renumbering look like a cascade.
    old_sections = [
        Section(heading="1.0 Purpose", paragraphs=[]),
        Section(heading="2.0 Equipment", paragraphs=[]),
    ]
    new_sections = [
        Section(heading="Page Header", paragraphs=[]),
        Section(heading="1.0 Purpose", paragraphs=[]),
        Section(heading="3.0 Equipment", paragraphs=[]),
    ]
    matches = [
        SectionMatch(old_index=0, new_index=1, score=1.0),
        SectionMatch(old_index=1, new_index=2, score=1.0),
    ]

    changes = detect_section_renumbering(
        matches, old_sections, new_sections, inserted_indices=[0], deleted_indices=[]
    )

    # The unnumbered insertion contributes 0, so the 2.0 -> 3.0 shift of 1 is
    # unexplained and stays deliberate.
    assert [c.change_type for c in changes] == ["section_renumbered"]


def test_omitting_the_new_arguments_reports_everything_as_deliberate():
    # Backwards compatibility: three-argument callers see unchanged behavior.
    old_sections = [Section(heading="2.0 Equipment", paragraphs=[])]
    new_sections = [Section(heading="3.0 Equipment", paragraphs=[])]
    matches = [SectionMatch(old_index=0, new_index=0, score=1.0)]

    changes = detect_section_renumbering(matches, old_sections, new_sections)

    assert [c.change_type for c in changes] == ["section_renumbered"]
    assert changes[0].reason == "Section renumbered from '2.0' to '3.0'."
```

- [ ] **Step 6: Run them to verify they fail**

Run: `cd backend && python -m pytest tests/test_section_structure.py -q`

Expected: the four tests asserting `section_renumbered_cascade` FAIL with `TypeError: detect_section_renumbering() got an unexpected keyword argument 'inserted_indices'`. The tests asserting the deliberate outcome will also fail with the same `TypeError` — they pass the new keyword arguments too. `test_omitting_the_new_arguments_reports_everything_as_deliberate` passes already, since it uses the current three-argument form.

- [ ] **Step 7: Implement the classification**

In `backend/app/section_structure.py`, find the signature and the first two lines of the loop:

```python
def detect_section_renumbering(
    matches: list[SectionMatch],
    old_sections: list[Section],
    new_sections: list[Section],
) -> list[Change]:
    changes: list[Change] = []
    for m in matches:
        old_heading = old_sections[m.old_index].heading
```

Replace with:

```python
def detect_section_renumbering(
    matches: list[SectionMatch],
    old_sections: list[Section],
    new_sections: list[Section],
    inserted_indices: list[int] | None = None,
    deleted_indices: list[int] | None = None,
) -> list[Change]:
    inserted_indices = inserted_indices or []
    deleted_indices = deleted_indices or []
    changes: list[Change] = []
    for m in matches:
        old_heading = old_sections[m.old_index].heading
```

Then find the block that builds the change:

```python
        change_type = "section_renumbered"
        changes.append(Change(
            change_id=str(uuid.uuid4()), section=old_heading, change_type=change_type,
            old_text=old_heading, new_text=new_heading, old_page=None, new_page=None,
            confidence=1.0, ai_risk_level=risk_rules.assign_risk(change_type),
            reason=f"Section renumbered from '{old_num}' to '{new_num}'.", source="Body",
        ))
```

Replace with:

```python
        change_type = "section_renumbered"
        reason = f"Section renumbered from '{old_num}' to '{new_num}'."
        # A number that moved by exactly the count of numbered sections added
        # above it (minus those removed) was not renumbered by anyone - it was
        # pushed. Only numbered sections count: the pseudo-sections this tool
        # generates (Page Header, Text Box N, Footnote N) carry no number.
        # Anything the arithmetic does not explain exactly stays deliberate,
        # so this over-reports rather than hides.
        inserted_above = sum(
            1 for i in inserted_indices
            if i < m.new_index and _split_heading_number(new_sections[i].heading) is not None
        )
        deleted_above = sum(
            1 for i in deleted_indices
            if i < m.old_index and _split_heading_number(old_sections[i].heading) is not None
        )
        expected_shift = inserted_above - deleted_above
        try:
            actual_shift = int(new_num.split(".")[0]) - int(old_num.split(".")[0])
        except ValueError:
            actual_shift = None
        if expected_shift != 0 and actual_shift == expected_shift:
            change_type = "section_renumbered_cascade"
            count = abs(expected_shift)
            verb = "added" if expected_shift > 0 else "removed"
            reason = (
                f"Section renumbered from '{old_num}' to '{new_num}' as a side effect of "
                f"{count} section{'' if count == 1 else 's'} {verb} above it; wording unchanged."
            )
        changes.append(Change(
            change_id=str(uuid.uuid4()), section=old_heading, change_type=change_type,
            old_text=old_heading, new_text=new_heading, old_page=None, new_page=None,
            confidence=1.0, ai_risk_level=risk_rules.assign_risk(change_type),
            reason=reason, source="Body",
        ))
```

- [ ] **Step 8: Run them to verify they pass**

Run: `cd backend && python -m pytest tests/test_section_structure.py -q`
Expected: all pass, including the nine new tests and the seven pre-existing three-argument renumbering tests, which must not need editing.

- [ ] **Step 9: Write the failing pipeline test**

The detector now accepts the indices, but `pipeline.py` does not yet pass them, so an end-to-end comparison still reports every cascade as deliberate.

Append to `backend/tests/test_pipeline.py`:

```python
def test_pipeline_reports_insertion_driven_renumbering_as_cascading(monkeypatch):
    # One insertion renumbers everything below it. Those rows are mechanical
    # consequences of a single edit and must be distinguishable from a
    # deliberate renumbering so a reviewer can filter them out.
    def fail_if_called(unresolved):
        raise AssertionError("no AI call expected for heading-only changes")

    monkeypatch.setattr(llm_classifier, "classify_changes_batch", fail_if_called)

    old_paragraphs = [
        Paragraph(text="1.0 Purpose"),
        Paragraph(text="This SOP defines the tablet compression process."),
        Paragraph(text="2.0 Equipment"),
        Paragraph(text="A rotary tablet press with standard tooling is used."),
        Paragraph(text="3.0 Records"),
        Paragraph(text="Batch records are retained for six years."),
    ]
    new_paragraphs = [
        Paragraph(text="1.0 Purpose"),
        Paragraph(text="This SOP defines the tablet compression process."),
        Paragraph(text="2.0 Safety"),
        Paragraph(text="Operators shall wear eye protection at all times."),
        Paragraph(text="3.0 Equipment"),
        Paragraph(text="A rotary tablet press with standard tooling is used."),
        Paragraph(text="4.0 Records"),
        Paragraph(text="Batch records are retained for six years."),
    ]

    result = pipeline.compare_documents(old_paragraphs, new_paragraphs, "old.txt", "new.txt")

    change_types = [c.change_type for c in result.changes]
    assert change_types.count("section_renumbered_cascade") == 2
    assert "section_renumbered" not in change_types
    assert "section_added" in change_types
```

- [ ] **Step 10: Run it to verify it fails**

Run: `cd backend && python -m pytest tests/test_pipeline.py -k cascading -v`
Expected: FAIL — `assert 0 == 2`, because `pipeline.py` still calls the detector with three arguments so `expected_shift` is always `0` and both rows report as `section_renumbered`.

- [ ] **Step 11: Pass the indices at the pipeline call site**

In `backend/app/pipeline.py`, find:

```python
    changes.extend(section_structure.detect_section_renumbering(
        match_result.matches, old_sections, new_sections
    ))
```

Replace with:

```python
    changes.extend(section_structure.detect_section_renumbering(
        match_result.matches, old_sections, new_sections,
        match_result.inserted_indices, match_result.deleted_indices,
    ))
```

- [ ] **Step 12: Run it to verify it passes**

Run: `cd backend && python -m pytest tests/test_pipeline.py -k cascading -v`
Expected: PASS.

- [ ] **Step 13: Run the full backend suite**

Run: `cd backend && python -m pytest -q`
Expected: **291 passed** (280 existing + 9 in `test_section_structure.py` + 1 in `test_risk_rules.py` + 1 in `test_pipeline.py`), no failures.

If a test outside the three files this task touches fails, stop and report it rather than editing that test. Applying this exact change and running the suite beforehand produced no such failures, so an unexpected one means something else is wrong.

- [ ] **Step 14: Commit**

```bash
git add backend/app/section_structure.py backend/app/risk_rules.py backend/app/pipeline.py backend/tests/test_section_structure.py backend/tests/test_risk_rules.py backend/tests/test_pipeline.py
git commit -m "feat: distinguish cascading renumbering from deliberate renumbering"
```
