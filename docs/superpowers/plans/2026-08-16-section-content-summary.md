# Section Added/Deleted Content Summary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tell a reviewer how much content an added or deleted section actually contains, by appending a short count summary to the existing reason text.

**Architecture:** One new private helper in `section_structure.py` counts non-table paragraphs and *distinct* tables (never table cells, which are stored one `Paragraph` per cell and would otherwise report a 4×3 table as "12 paragraphs"). Both `detect_section_added` and `detect_section_deleted` append its output to the `reason` string they already build. Because `reason` is already persisted, exported to JSON and CSV, and displayed on the Detailed Changes page, the summary reaches every surface with no schema migration and no changes outside this one module.

**Tech Stack:** Python, FastAPI backend, pytest.

## Global Constraints

- Count non-table paragraphs as paragraphs, and count **distinct `table_position.table_id` values** as tables. Never count table cells as paragraphs. (spec: "The counting problem")
- A section with neither paragraphs nor tables produces exactly `"No content."` — never an omitted or empty summary. (spec: "Decision")
- Count `remaining_paragraphs` (the post-`excluded_paragraph_ids` list already computed in both detectors), never `section.paragraphs`, so the summary matches the row's own `old_text`/`new_text`. (spec: "Count `remaining_paragraphs`")
- Exactly one space separates the existing sentence from the summary, and the summary ends in a period. (spec: "Design per component")
- `Paragraph` must be added to this module's `from app.models import ...` line — it is not currently imported, and the helper's annotation names it. (spec: "Import change")
- Do not add a summary to `detect_section_heading_changed`, `detect_section_renumbering`, or `detect_section_reordering`. Do not add any new `Change` field, database column, or export/frontend change. (spec: "Unaffected", "Out of Scope")

---

### Task 1: Content summary on section added/deleted reasons

**Files:**
- Modify: `backend/app/section_structure.py`
- Test: `backend/tests/test_section_structure.py`

**Interfaces:**
- Produces: `_summarize_section_content(paragraphs: list[Paragraph]) -> str` in `backend/app/section_structure.py`. Returns `"No content."`, or a comma-joined count string ending in a period, e.g. `"1 paragraph."`, `"2 tables."`, `"1 paragraph, 1 table."`.
- Consumes: `remaining_paragraphs`, a local already computed in both `detect_section_added` and `detect_section_deleted`. No signature changes to either detector.

`backend/tests/test_section_structure.py` currently imports `from app.models import Section, Paragraph, SectionMatch` — `TableCoordinate` is **not** imported and the new tests need it.

- [ ] **Step 1: Update the two existing tests that assert the old reason text**

Two existing tests pin the exact reason strings and will otherwise fail. Both are correct to update — the reason genuinely changes.

In `backend/tests/test_section_structure.py`, inside `test_new_section_with_body_is_detected` (the section has two body paragraphs), find:

```python
    assert c.reason == "New section added: '5.0 Environmental Monitoring'."
```

Replace with:

```python
    assert c.reason == "New section added: '5.0 Environmental Monitoring'. 2 paragraphs."
```

Inside `test_deleted_section_with_body_is_detected` (the section has one body paragraph), find:

```python
    assert c.reason == "Section deleted: '8.0 Deviation Handling'."
```

Replace with:

```python
    assert c.reason == "Section deleted: '8.0 Deviation Handling'. 1 paragraph."
```

- [ ] **Step 2: Add `TableCoordinate` to the test file's imports**

Find the first line of `backend/tests/test_section_structure.py`:

```python
from app.models import Section, Paragraph, SectionMatch
```

Replace with:

```python
from app.models import Section, Paragraph, SectionMatch, TableCoordinate
```

- [ ] **Step 3: Import the new helper in the test file**

Find the existing import block:

```python
from app.section_structure import (
    detect_section_renumbering, detect_section_reordering,
    detect_section_added, detect_section_deleted, detect_section_heading_changed,
)
```

Replace with:

```python
from app.section_structure import (
    detect_section_renumbering, detect_section_reordering,
    detect_section_added, detect_section_deleted, detect_section_heading_changed,
    _summarize_section_content,
)
```

- [ ] **Step 4: Write the failing tests**

Append to `backend/tests/test_section_structure.py`:

```python
def _table_cell(text, table_id, row=0, col=0):
    return Paragraph(
        text=text,
        from_table=True,
        table_position=TableCoordinate(table_id=table_id, row=row, col=col),
    )


def test_summary_counts_paragraphs_only():
    paragraphs = [Paragraph(text="first"), Paragraph(text="second")]
    assert _summarize_section_content(paragraphs) == "2 paragraphs."


def test_summary_uses_singular_for_one_paragraph():
    assert _summarize_section_content([Paragraph(text="only one")]) == "1 paragraph."


def test_summary_counts_a_table_once_not_once_per_cell():
    # The miscount this whole feature exists to avoid: a 4x3 table is stored as
    # twelve Paragraph objects sharing one table_id, and must read as "1 table"
    # rather than "12 paragraphs".
    cells = [_table_cell(f"cell {i}", table_id=0, row=i // 3, col=i % 3) for i in range(12)]
    assert _summarize_section_content(cells) == "1 table."


def test_summary_counts_paragraphs_and_tables_together():
    paragraphs = [Paragraph(text="intro")]
    paragraphs += [_table_cell(f"cell {i}", table_id=0) for i in range(6)]
    assert _summarize_section_content(paragraphs) == "1 paragraph, 1 table."


def test_summary_counts_distinct_tables():
    paragraphs = [
        _table_cell("a", table_id=0),
        _table_cell("b", table_id=0),
        _table_cell("c", table_id=1),
    ]
    assert _summarize_section_content(paragraphs) == "2 tables."


def test_summary_of_empty_section_is_no_content():
    assert _summarize_section_content([]) == "No content."


def test_section_added_reason_includes_content_summary():
    new_sections = [
        Section(heading="4.0 Procedure", paragraphs=[
            Paragraph(text="Compression force shall be maintained at 15 kN."),
            _table_cell("Parameter", table_id=0),
            _table_cell("Target", table_id=0),
        ]),
    ]

    changes = detect_section_added([0], new_sections)

    assert changes[0].reason == "New section added: '4.0 Procedure'. 1 paragraph, 1 table."


def test_section_deleted_reason_includes_content_summary():
    old_sections = [
        Section(heading="7.0 References", paragraphs=[
            Paragraph(text="Equipment Manual EM-004."),
            Paragraph(text="Quality Manual QM-001."),
        ]),
    ]

    changes = detect_section_deleted([0], old_sections)

    assert changes[0].reason == "Section deleted: '7.0 References'. 2 paragraphs."


def test_heading_only_section_added_reason_says_no_content():
    changes = detect_section_added([0], [Section(heading="9.0 Training Log", paragraphs=[])])
    assert changes[0].reason == "New section added: '9.0 Training Log'. No content."


def test_heading_only_section_deleted_reason_says_no_content():
    changes = detect_section_deleted([0], [Section(heading="7.0 References", paragraphs=[])])
    assert changes[0].reason == "Section deleted: '7.0 References'. No content."


def test_section_added_summary_counts_only_remaining_paragraphs():
    # Content that merely relocated into this section is excluded from the row's
    # new_text and reported separately as a move, so the summary must exclude it
    # too - otherwise the count would contradict the text displayed beside it.
    relocated = Paragraph(text="this moved in from another section")
    genuinely_new_one = Paragraph(text="genuinely new one")
    genuinely_new_two = Paragraph(text="genuinely new two")
    new_sections = [
        Section(heading="5.0 Sampling", paragraphs=[genuinely_new_one, relocated, genuinely_new_two]),
    ]

    changes = detect_section_added(
        [0], new_sections, excluded_paragraph_ids={id(relocated)}
    )

    assert changes[0].reason == "New section added: '5.0 Sampling'. 2 paragraphs."
    assert changes[0].new_text == "5.0 Sampling\ngenuinely new one\ngenuinely new two"
```

- [ ] **Step 5: Run the tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_section_structure.py -q`

Expected: FAIL at collection with `ImportError: cannot import name '_summarize_section_content' from 'app.section_structure'`, because the helper does not exist yet. This single import error prevents the whole module from running, which is expected at this stage.

- [ ] **Step 6: Add `Paragraph` to the module's imports**

In `backend/app/section_structure.py`, find:

```python
from app.models import Change, Section, SectionMatch
```

Replace with:

```python
from app.models import Change, Paragraph, Section, SectionMatch
```

This is required, not cosmetic: the helper's annotation names `Paragraph`. On this project's Python (3.14) PEP 649 defers annotation evaluation so an undefined name raises nothing at import or call time — it fails only under `typing.get_type_hints()` — but it raises `NameError` at import on Python 3.13 and earlier. Leaving it unimported would be a silent latent break.

- [ ] **Step 7: Add the helper**

In `backend/app/section_structure.py`, find the start of the added-section detector:

```python
def detect_section_added(
```

Insert the helper immediately above it, leaving two blank lines between the helper and `detect_section_added`:

```python
def _summarize_section_content(paragraphs: list[Paragraph]) -> str:
    # Table content is stored one Paragraph per CELL, all cells of one table
    # sharing a table_id - so counting raw paragraphs would report a 4x3 table
    # as "12 paragraphs". Count distinct tables instead. Guarding on
    # table_position is defensive: extraction always sets it alongside
    # from_table, but a table paragraph without one should be skipped in the
    # tally rather than raising mid-comparison.
    body_count = sum(1 for p in paragraphs if not p.from_table)
    table_ids = {
        p.table_position.table_id
        for p in paragraphs
        if p.from_table and p.table_position is not None
    }
    parts = []
    if body_count:
        parts.append(f"{body_count} paragraph" + ("" if body_count == 1 else "s"))
    if table_ids:
        parts.append(f"{len(table_ids)} table" + ("" if len(table_ids) == 1 else "s"))
    if not parts:
        return "No content."
    return ", ".join(parts) + "."


def detect_section_added(
```

- [ ] **Step 8: Append the summary in `detect_section_added`**

In `backend/app/section_structure.py`, inside `detect_section_added`, find:

```python
            reason=f"New section added: '{section.heading}'.", source=source,
```

Replace with:

```python
            reason=(
                f"New section added: '{section.heading}'. "
                f"{_summarize_section_content(remaining_paragraphs)}"
            ),
            source=source,
```

- [ ] **Step 9: Append the summary in `detect_section_deleted`**

In `backend/app/section_structure.py`, inside `detect_section_deleted`, find:

```python
            reason=f"Section deleted: '{section.heading}'.", source=source,
```

Replace with:

```python
            reason=(
                f"Section deleted: '{section.heading}'. "
                f"{_summarize_section_content(remaining_paragraphs)}"
            ),
            source=source,
```

- [ ] **Step 10: Run the tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_section_structure.py -q`
Expected: all tests in the module pass, including the two updated in Step 1 and the eleven added in Step 4.

- [ ] **Step 11: Run the full backend suite**

Run: `cd backend && python -m pytest -q`
Expected: **277 passed** (266 existing + 11 new), no failures.

If any test outside `test_section_structure.py` fails, stop and report it rather than editing that test — a suite-wide sweep confirmed only the two tests updated in Step 1 depend on these reason strings, so an unexpected third failure means something else is wrong.

- [ ] **Step 12: Commit**

```bash
git add backend/app/section_structure.py backend/tests/test_section_structure.py
git commit -m "feat: summarize paragraph and table counts on added/deleted sections"
```
