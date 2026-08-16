# Table Cell Details in Change Presentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface the already-extracted `TableCoordinate` data (table ID, row, column) all the way through to the Detailed Changes report, persistence, and export — so a reviewer can see exactly which table cell a change came from.

**Architecture:** `Change` gains `old_table_position`/`new_table_position` (both `Optional[TableCoordinate]`), computed in `pipeline.py` at the same 4 sites that already compute `source`. The data flows through the existing `Change` → SQLite → export → frontend path, mirroring exactly how the `source` field was added earlier — a DB migration for the real, live database, JSON export as structured data, CSV export and the frontend as one compact formatted column.

**Tech Stack:** Python 3, pytest, sqlite3 — no new dependencies.

## Global Constraints

- New fields: `Change.old_table_position: Optional[TableCoordinate] = None`, `Change.new_table_position: Optional[TableCoordinate] = None` (reusing the existing `TableCoordinate` dataclass — no new dataclass).
- Computed at all 4 existing `Change`-construction sites in `pipeline.py`, reading `paragraph.table_position` directly (already `None` for body paragraphs, no extra conditional needed).
- These values are set once at `Change` creation and must NOT be touched by the later AI-classification resolution loop (same as `source` already isn't).
- DB: 6 new nullable `INTEGER` columns on `changes` — `old_table_id`, `old_table_row`, `old_table_col`, `new_table_id`, `new_table_row`, `new_table_col`. Idempotent migration required (mirrors `_ensure_changes_source_column`) since `backend/app.db` is a real, live file with existing rows.
- Presence signaled by checking `old_table_id is not None` / `new_table_id is not None` alone (all 3 values of one side are always written together, never partially).
- JSON export: `"old_table_position"`/`"new_table_position"` keys, each `{"table_id": int, "row": int, "col": int}` or `null`.
- CSV export and frontend: one compact `"Table Cell"` / `"table_cell"` column. Format: empty string when both positions are `None`; `"Table {id}, Row {row}, Col {col}"` when old and new positions are identical (or only one side is populated); `"Table {id}, Row {row}, Col {col} → Table {id}, Row {row}, Col {col}"` only when old and new genuinely differ.
- The compact-format logic is implemented twice, independently — once in `backend/app/export.py` (operating on `TableCoordinate` objects) and once in `frontend/logic.py` (operating on JSON dicts) — because the frontend never imports backend code, it only receives JSON over HTTP. Keep both implementations producing identical output for identical input.
- Reference: `docs/superpowers/specs/2026-08-14-table-cell-details-design.md`.

---

### Task 1: Add old_table_position/new_table_position to Change

**Files:**
- Modify: `backend/app/models.py`
- Modify: `backend/tests/test_models.py`

**Interfaces:**
- Produces: `Change.old_table_position: Optional[TableCoordinate] = None`, `Change.new_table_position: Optional[TableCoordinate] = None` in `app/models.py`. Consumed by Task 2, Task 3, Task 4.

- [ ] **Step 1: Write the failing test**

In `backend/tests/test_models.py`, replace the existing import line:

```python
from app.models import (
    Paragraph, Section, SectionMatch, SectionMatchResult, MovedParagraph,
    RegexDetection, LLMClassification, Change, ComparisonSummary,
    ComparisonResult, build_summary,
)
```

with:

```python
from app.models import (
    Paragraph, Section, SectionMatch, SectionMatchResult, MovedParagraph,
    RegexDetection, LLMClassification, Change, ComparisonSummary,
    ComparisonResult, build_summary, TableCoordinate,
)
```

Append these test functions:

```python
def test_change_table_positions_default_to_none():
    c = Change(
        change_id="c1", section="1.0 Scope", change_type="numeric_change",
        old_text="95%", new_text="98%", old_page=1, new_page=1,
        confidence=1.0, ai_risk_level="High", reason="value changed",
    )
    assert c.old_table_position is None
    assert c.new_table_position is None


def test_change_can_carry_table_positions():
    old_pos = TableCoordinate(table_id=0, row=1, col=1)
    new_pos = TableCoordinate(table_id=0, row=1, col=1)
    c = Change(
        change_id="c1", section="2.0 Acceptance Criteria", change_type="numeric_change",
        old_text="95%", new_text="98%", old_page=1, new_page=1,
        confidence=1.0, ai_risk_level="High", reason="value changed",
        old_table_position=old_pos, new_table_position=new_pos,
    )
    assert c.old_table_position is old_pos
    assert c.new_table_position is new_pos
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `backend/`): `python -m pytest tests/test_models.py -v`
Expected: the 2 new tests FAIL with `TypeError` (`Change` doesn't accept `old_table_position`/`new_table_position` yet). Every pre-existing test still PASSES.

- [ ] **Step 3: Write the implementation**

In `backend/app/models.py`, find:

```python
@dataclass
class Change:
    change_id: str
    section: str
    change_type: str
    old_text: str
    new_text: str
    old_page: Optional[int]
    new_page: Optional[int]
    confidence: float
    ai_risk_level: str
    reason: str
    reviewer_risk_level: Optional[str] = None
    reviewer_comment: Optional[str] = None
    accepted: bool = False
    source: str = "Body"
```

Replace with:

```python
@dataclass
class Change:
    change_id: str
    section: str
    change_type: str
    old_text: str
    new_text: str
    old_page: Optional[int]
    new_page: Optional[int]
    confidence: float
    ai_risk_level: str
    reason: str
    reviewer_risk_level: Optional[str] = None
    reviewer_comment: Optional[str] = None
    accepted: bool = False
    source: str = "Body"
    old_table_position: Optional[TableCoordinate] = None
    new_table_position: Optional[TableCoordinate] = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_models.py -v`
Expected: PASS, all tests.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models.py backend/tests/test_models.py
git commit -m "feat: add old_table_position/new_table_position to Change"
```

---

### Task 2: Compute table positions in the comparison pipeline

**Files:**
- Modify: `backend/app/pipeline.py`
- Modify: `backend/tests/test_pipeline.py`

**Interfaces:**
- Consumes: `Change.old_table_position`/`new_table_position` from Task 1.
- Produces: nothing new for later tasks — `compare_documents`'s returned `Change` objects now have these fields populated. Consumed by Task 3 (persistence) and Task 4 (export/frontend) only insofar as they read whatever `Change` objects already carry.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_pipeline.py` (uses the existing `Paragraph` import at the top of the file — add `TableCoordinate` to it):

Find:
```python
from app.models import Paragraph, LLMClassification
```
Replace with:
```python
from app.models import Paragraph, LLMClassification, TableCoordinate
```

Append these test functions:

```python
def test_table_cell_edit_preserves_table_position_on_both_sides():
    position = TableCoordinate(table_id=0, row=1, col=1)
    old_paragraphs = [Paragraph(text="Weigh 10 mg of sample.", from_table=True, table_position=position)]
    new_paragraphs = [Paragraph(text="Weigh 20 mg of sample.", from_table=True, table_position=position)]

    result = pipeline.compare_documents(old_paragraphs, new_paragraphs, "old.docx", "new.docx")

    assert len(result.changes) == 1
    change = result.changes[0]
    assert change.old_table_position == position
    assert change.new_table_position == position


def test_table_row_addition_only_sets_new_table_position():
    position = TableCoordinate(table_id=0, row=3, col=0)
    old_paragraphs = []
    new_paragraphs = [Paragraph(text="New Row Value", from_table=True, table_position=position)]

    result = pipeline.compare_documents(old_paragraphs, new_paragraphs, "old.docx", "new.docx")

    assert len(result.changes) == 1
    change = result.changes[0]
    assert change.old_table_position is None
    assert change.new_table_position == position


def test_table_row_deletion_only_sets_old_table_position():
    position = TableCoordinate(table_id=0, row=3, col=0)
    old_paragraphs = [Paragraph(text="Old Row Value", from_table=True, table_position=position)]
    new_paragraphs = []

    result = pipeline.compare_documents(old_paragraphs, new_paragraphs, "old.docx", "new.docx")

    assert len(result.changes) == 1
    change = result.changes[0]
    assert change.old_table_position == position
    assert change.new_table_position is None


def test_body_paragraph_addition_has_no_table_position():
    old_paragraphs = []
    new_paragraphs = [Paragraph(text="New body sentence.")]

    result = pipeline.compare_documents(old_paragraphs, new_paragraphs, "old.docx", "new.docx")

    assert len(result.changes) == 1
    change = result.changes[0]
    assert change.old_table_position is None
    assert change.new_table_position is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_pipeline.py -v`
Expected: the 4 new tests FAIL with `AttributeError` (`Change` objects don't have `old_table_position`/`new_table_position` populated — wait, they exist as `None` from Task 1's default, so the edit/add/delete tests specifically will fail their `== position` assertions, not with an `AttributeError`). Every pre-existing test in the file still PASSES.

- [ ] **Step 3: Wire table positions into all 4 Change-construction sites**

In `backend/app/pipeline.py`, find `_build_paragraph_changes`:

```python
def _build_paragraph_changes(
    section_heading: str, old_p: Paragraph, new_p: Paragraph
) -> tuple[list[Change], dict[str, list[str]]]:
    source = "Table" if (old_p.from_table or new_p.from_table) else "Body"
    detections = regex_detectors.detect_all_regex_changes(old_p.text, new_p.text)
    changes: list[Change] = []
    for detection in detections:
        changes.append(Change(
            change_id=str(uuid.uuid4()), section=section_heading, change_type=detection.change_type,
            old_text=old_p.text, new_text=new_p.text, old_page=old_p.page, new_page=new_p.page,
            confidence=detection.confidence, ai_risk_level=risk_rules.assign_risk(detection.change_type),
            reason=detection.reason, source=source,
        ))

    already_detected_by_id: dict[str, list[str]] = {}
    stripped_old, stripped_new = regex_detectors.strip_detected_values(old_p.text, new_p.text, detections)
    if stripped_old != stripped_new:
        pending_id = str(uuid.uuid4())
        changes.append(Change(
            change_id=pending_id, section=section_heading, change_type="pending_llm_classification",
            old_text=old_p.text, new_text=new_p.text, old_page=old_p.page, new_page=new_p.page,
            confidence=0.0, ai_risk_level="Medium", reason="", source=source,
        ))
        already_detected_by_id[pending_id] = [d.change_type for d in detections]

    return changes, already_detected_by_id
```

Replace with:

```python
def _build_paragraph_changes(
    section_heading: str, old_p: Paragraph, new_p: Paragraph
) -> tuple[list[Change], dict[str, list[str]]]:
    source = "Table" if (old_p.from_table or new_p.from_table) else "Body"
    detections = regex_detectors.detect_all_regex_changes(old_p.text, new_p.text)
    changes: list[Change] = []
    for detection in detections:
        changes.append(Change(
            change_id=str(uuid.uuid4()), section=section_heading, change_type=detection.change_type,
            old_text=old_p.text, new_text=new_p.text, old_page=old_p.page, new_page=new_p.page,
            confidence=detection.confidence, ai_risk_level=risk_rules.assign_risk(detection.change_type),
            reason=detection.reason, source=source,
            old_table_position=old_p.table_position, new_table_position=new_p.table_position,
        ))

    already_detected_by_id: dict[str, list[str]] = {}
    stripped_old, stripped_new = regex_detectors.strip_detected_values(old_p.text, new_p.text, detections)
    if stripped_old != stripped_new:
        pending_id = str(uuid.uuid4())
        changes.append(Change(
            change_id=pending_id, section=section_heading, change_type="pending_llm_classification",
            old_text=old_p.text, new_text=new_p.text, old_page=old_p.page, new_page=new_p.page,
            confidence=0.0, ai_risk_level="Medium", reason="", source=source,
            old_table_position=old_p.table_position, new_table_position=new_p.table_position,
        ))
        already_detected_by_id[pending_id] = [d.change_type for d in detections]

    return changes, already_detected_by_id
```

Then find the moved-paragraph loop:

```python
    for mv in moved:
        source = "Table" if (mv.old_paragraph.from_table or mv.new_paragraph.from_table) else "Body"
        if source == "Table":
            change_type = "moved_table_content"
            reason = f"Table content moved from '{mv.old_section}' to '{mv.new_section}'."
        else:
            change_type = "moved_paragraph"
            reason = f"Paragraph moved from '{mv.old_section}' to '{mv.new_section}'."
        changes.append(Change(
            change_id=str(uuid.uuid4()), section=f"{mv.old_section} -> {mv.new_section}",
            change_type=change_type, old_text=mv.old_paragraph.text, new_text=mv.new_paragraph.text,
            old_page=mv.old_paragraph.page, new_page=mv.new_paragraph.page, confidence=mv.score,
            ai_risk_level=risk_rules.assign_risk(change_type),
            reason=reason, source=source,
        ))
```

Replace with:

```python
    for mv in moved:
        source = "Table" if (mv.old_paragraph.from_table or mv.new_paragraph.from_table) else "Body"
        if source == "Table":
            change_type = "moved_table_content"
            reason = f"Table content moved from '{mv.old_section}' to '{mv.new_section}'."
        else:
            change_type = "moved_paragraph"
            reason = f"Paragraph moved from '{mv.old_section}' to '{mv.new_section}'."
        changes.append(Change(
            change_id=str(uuid.uuid4()), section=f"{mv.old_section} -> {mv.new_section}",
            change_type=change_type, old_text=mv.old_paragraph.text, new_text=mv.new_paragraph.text,
            old_page=mv.old_paragraph.page, new_page=mv.new_paragraph.page, confidence=mv.score,
            ai_risk_level=risk_rules.assign_risk(change_type),
            reason=reason, source=source,
            old_table_position=mv.old_paragraph.table_position, new_table_position=mv.new_paragraph.table_position,
        ))
```

Then find the deleted-paragraph loop:

```python
    for p, section in remaining_deletes:
        if id(p) in whole_deleted_paragraph_ids:
            continue
        source = "Table" if p.from_table else "Body"
        if source == "Table":
            change_type = "deleted_table_content"
            reason = "Table content removed."
        else:
            change_type = "deleted_paragraph"
            reason = "Paragraph removed."
        changes.append(Change(
            change_id=str(uuid.uuid4()), section=section, change_type=change_type,
            old_text=p.text, new_text="", old_page=p.page, new_page=None,
            confidence=1.0, ai_risk_level=risk_rules.assign_risk(change_type),
            reason=reason, source=source,
        ))
```

Replace with:

```python
    for p, section in remaining_deletes:
        if id(p) in whole_deleted_paragraph_ids:
            continue
        source = "Table" if p.from_table else "Body"
        if source == "Table":
            change_type = "deleted_table_content"
            reason = "Table content removed."
        else:
            change_type = "deleted_paragraph"
            reason = "Paragraph removed."
        changes.append(Change(
            change_id=str(uuid.uuid4()), section=section, change_type=change_type,
            old_text=p.text, new_text="", old_page=p.page, new_page=None,
            confidence=1.0, ai_risk_level=risk_rules.assign_risk(change_type),
            reason=reason, source=source,
            old_table_position=p.table_position, new_table_position=None,
        ))
```

Then find the added-paragraph loop:

```python
    for p, section in remaining_inserts:
        if id(p) in whole_inserted_paragraph_ids:
            continue
        source = "Table" if p.from_table else "Body"
        if source == "Table":
            change_type = "added_table_content"
            reason = "New table content added."
        else:
            change_type = "added_paragraph"
            reason = "New paragraph added."
        changes.append(Change(
            change_id=str(uuid.uuid4()), section=section, change_type=change_type,
            old_text="", new_text=p.text, old_page=None, new_page=p.page,
            confidence=1.0, ai_risk_level=risk_rules.assign_risk(change_type),
            reason=reason, source=source,
        ))
```

Replace with:

```python
    for p, section in remaining_inserts:
        if id(p) in whole_inserted_paragraph_ids:
            continue
        source = "Table" if p.from_table else "Body"
        if source == "Table":
            change_type = "added_table_content"
            reason = "New table content added."
        else:
            change_type = "added_paragraph"
            reason = "New paragraph added."
        changes.append(Change(
            change_id=str(uuid.uuid4()), section=section, change_type=change_type,
            old_text="", new_text=p.text, old_page=None, new_page=p.page,
            confidence=1.0, ai_risk_level=risk_rules.assign_risk(change_type),
            reason=reason, source=source,
            old_table_position=None, new_table_position=p.table_position,
        ))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_pipeline.py -v`
Expected: PASS, all tests — the 4 new tests and every pre-existing test in the file (in particular the existing `test_table_cell_deletion_gets_table_labeled_change_type`, `test_table_cell_addition_gets_table_labeled_change_type`, `test_table_cell_with_precise_regex_change_keeps_precise_type`, `test_body_paragraph_addition_keeps_generic_change_type` — none of these assert on `old_table_position`/`new_table_position`, so they're unaffected by this addition).

- [ ] **Step 5: Run the full backend suite**

Run (from `backend/`): `python -m pytest -v`
Expected: PASS, all tests, no regressions.

- [ ] **Step 6: Manually verify against the real `TableHeaderVariantDemo_v1.docx`/`_v2.docx` fixtures**

If these files exist in `test-documents/docx/` (created during earlier manual testing this session), use them; otherwise skip this step and note it in your report. From `backend/`:

```python
python -c "
from app.extraction import extract_text
from app.pipeline import compare_documents

old = extract_text('../test-documents/docx/TableHeaderVariantDemo_v1.docx', 'docx')
new = extract_text('../test-documents/docx/TableHeaderVariantDemo_v2.docx', 'docx')
result = compare_documents(old, new, 'v1.docx', 'v2.docx')
for c in result.changes:
    if c.source == 'Table':
        print(c.change_type, c.old_table_position, '->', c.new_table_position)
"
```

Expected: the table-sourced change (an edited cell) shows a non-`None` `old_table_position` and `new_table_position` with matching `table_id`/`row`/`col` (same cell, content changed). Include this output in your report.

- [ ] **Step 7: Commit**

```bash
git add backend/app/pipeline.py backend/tests/test_pipeline.py
git commit -m "feat: compute old/new table positions for table-sourced changes"
```

---

### Task 3: Persist table positions to SQLite

**Files:**
- Modify: `backend/app/db.py`
- Modify: `backend/app/repository.py`
- Modify: `backend/tests/test_repository.py`

**Interfaces:**
- Consumes: `Change.old_table_position`/`new_table_position` from Task 1 (Task 2's pipeline wiring is not required for this task — tests here construct `Change` objects directly, same pattern the existing `source` persistence tests already use).
- Produces: nothing new for later tasks — `repository.save_comparison`/`get_comparison` now round-trip these fields transparently, same interface signatures as before.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/test_repository.py`, add `TableCoordinate` to the existing import line. Find:
```python
from app.models import Change, ComparisonResult, build_summary
```
Replace with:
```python
from app.models import Change, ComparisonResult, build_summary, TableCoordinate
```

Append these test functions:

```python
def test_save_and_get_comparison_round_trip_preserves_table_positions():
    conn = make_conn()
    old_id = repository.create_document(conn, "old.docx", "docx", "/data/old.docx")
    new_id = repository.create_document(conn, "new.docx", "docx", "/data/new.docx")

    old_pos = TableCoordinate(table_id=0, row=1, col=1)
    new_pos = TableCoordinate(table_id=0, row=1, col=1)
    changes = [
        Change(
            change_id="ch-1", section="2.0 Acceptance Criteria", change_type="numeric_change",
            old_text="95%", new_text="98%", old_page=1, new_page=1,
            confidence=1.0, ai_risk_level="High", reason="value changed", source="Table",
            old_table_position=old_pos, new_table_position=new_pos,
        ),
    ]
    comparison = ComparisonResult(
        comparison_id="cmp-table-1", old_document="old.docx", new_document="new.docx",
        summary=build_summary(changes), changes=changes,
    )

    repository.save_comparison(conn, comparison, old_id, new_id)
    fetched = repository.get_comparison(conn, "cmp-table-1")

    assert fetched.changes[0].old_table_position == old_pos
    assert fetched.changes[0].new_table_position == new_pos


def test_save_and_get_comparison_defaults_table_positions_to_none():
    conn = make_conn()
    old_id = repository.create_document(conn, "old.txt", "txt", "/data/old.txt")
    new_id = repository.create_document(conn, "new.txt", "txt", "/data/new.txt")

    changes = [
        Change(
            change_id="ch-1", section="1.0 Scope", change_type="numeric_change",
            old_text="95%", new_text="98%", old_page=1, new_page=1,
            confidence=1.0, ai_risk_level="High", reason="value changed",
        ),
    ]
    comparison = ComparisonResult(
        comparison_id="cmp-table-2", old_document="old.txt", new_document="new.txt",
        summary=build_summary(changes), changes=changes,
    )

    repository.save_comparison(conn, comparison, old_id, new_id)
    fetched = repository.get_comparison(conn, "cmp-table-2")

    assert fetched.changes[0].old_table_position is None
    assert fetched.changes[0].new_table_position is None


def test_save_and_get_comparison_round_trip_with_only_new_table_position():
    conn = make_conn()
    old_id = repository.create_document(conn, "old.docx", "docx", "/data/old.docx")
    new_id = repository.create_document(conn, "new.docx", "docx", "/data/new.docx")

    new_pos = TableCoordinate(table_id=1, row=3, col=0)
    changes = [
        Change(
            change_id="ch-1", section="2.0 Acceptance Criteria", change_type="added_table_content",
            old_text="", new_text="Microbial Limits", old_page=None, new_page=1,
            confidence=1.0, ai_risk_level="Medium", reason="New table content added.", source="Table",
            old_table_position=None, new_table_position=new_pos,
        ),
    ]
    comparison = ComparisonResult(
        comparison_id="cmp-table-3", old_document="old.docx", new_document="new.docx",
        summary=build_summary(changes), changes=changes,
    )

    repository.save_comparison(conn, comparison, old_id, new_id)
    fetched = repository.get_comparison(conn, "cmp-table-3")

    assert fetched.changes[0].old_table_position is None
    assert fetched.changes[0].new_table_position == new_pos


def test_existing_database_missing_table_position_columns_gets_migrated(tmp_path):
    db_path = str(tmp_path / "legacy_table.db")
    # Simulate a database created before the table-position columns existed - this
    # is exactly the shape of the real backend/app.db file found during planning
    # for the earlier `source` column migration, now missing these 6 columns too.
    legacy_conn = sqlite3.connect(db_path)
    legacy_conn.execute("""
        CREATE TABLE changes (
            id TEXT PRIMARY KEY, comparison_id TEXT NOT NULL, section TEXT, change_type TEXT,
            old_text TEXT, new_text TEXT, old_page INTEGER, new_page INTEGER, confidence REAL,
            ai_risk_level TEXT, reviewer_risk_level TEXT, reason TEXT, reviewer_comment TEXT,
            accepted INTEGER DEFAULT 0, source TEXT DEFAULT 'Body'
        )
    """)
    legacy_conn.commit()
    legacy_conn.close()

    conn = get_connection(db_path)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(changes)").fetchall()}

    for column in ("old_table_id", "old_table_row", "old_table_col", "new_table_id", "new_table_row", "new_table_col"):
        assert column in columns
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_repository.py -v`
Expected: the 4 new tests FAIL — the migration test fails because the columns don't exist yet; the round-trip tests fail because `save_comparison`/`_row_to_change` don't handle the new fields yet (likely an `sqlite3.OperationalError` for unknown columns, or the fetched positions simply not matching). Every pre-existing test still PASSES.

- [ ] **Step 3: Add the DB migration**

In `backend/app/db.py`, find the `SCHEMA` string's `changes` table definition:

```python
CREATE TABLE IF NOT EXISTS changes (
    id TEXT PRIMARY KEY,
    comparison_id TEXT NOT NULL,
    section TEXT,
    change_type TEXT,
    old_text TEXT,
    new_text TEXT,
    old_page INTEGER,
    new_page INTEGER,
    confidence REAL,
    ai_risk_level TEXT,
    reviewer_risk_level TEXT,
    reason TEXT,
    reviewer_comment TEXT,
    accepted INTEGER DEFAULT 0,
    source TEXT DEFAULT 'Body'
);
"""
```

Replace with:

```python
CREATE TABLE IF NOT EXISTS changes (
    id TEXT PRIMARY KEY,
    comparison_id TEXT NOT NULL,
    section TEXT,
    change_type TEXT,
    old_text TEXT,
    new_text TEXT,
    old_page INTEGER,
    new_page INTEGER,
    confidence REAL,
    ai_risk_level TEXT,
    reviewer_risk_level TEXT,
    reason TEXT,
    reviewer_comment TEXT,
    accepted INTEGER DEFAULT 0,
    source TEXT DEFAULT 'Body',
    old_table_id INTEGER,
    old_table_row INTEGER,
    old_table_col INTEGER,
    new_table_id INTEGER,
    new_table_row INTEGER,
    new_table_col INTEGER
);
"""
```

Then find:

```python
def _ensure_changes_source_column(conn: sqlite3.Connection) -> None:
    # CREATE TABLE IF NOT EXISTS above only applies to brand-new databases - it does
    # not add columns to a changes table that already exists from before this field
    # was introduced. Any pre-existing database (including the real backend/app.db
    # file already in use) needs this explicit, idempotent migration instead.
    columns = {row[1] for row in conn.execute("PRAGMA table_info(changes)").fetchall()}
    if "source" not in columns:
        conn.execute("ALTER TABLE changes ADD COLUMN source TEXT DEFAULT 'Body'")
        conn.commit()


def get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _ensure_changes_source_column(conn)
    return conn
```

Replace with:

```python
def _ensure_changes_source_column(conn: sqlite3.Connection) -> None:
    # CREATE TABLE IF NOT EXISTS above only applies to brand-new databases - it does
    # not add columns to a changes table that already exists from before this field
    # was introduced. Any pre-existing database (including the real backend/app.db
    # file already in use) needs this explicit, idempotent migration instead.
    columns = {row[1] for row in conn.execute("PRAGMA table_info(changes)").fetchall()}
    if "source" not in columns:
        conn.execute("ALTER TABLE changes ADD COLUMN source TEXT DEFAULT 'Body'")
        conn.commit()


def _ensure_changes_table_position_columns(conn: sqlite3.Connection) -> None:
    # Same rationale as _ensure_changes_source_column above - a pre-existing changes
    # table (including the real backend/app.db file) needs these added explicitly.
    columns = {row[1] for row in conn.execute("PRAGMA table_info(changes)").fetchall()}
    new_columns = [
        "old_table_id", "old_table_row", "old_table_col",
        "new_table_id", "new_table_row", "new_table_col",
    ]
    for column in new_columns:
        if column not in columns:
            conn.execute(f"ALTER TABLE changes ADD COLUMN {column} INTEGER")
    conn.commit()


def get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _ensure_changes_source_column(conn)
    _ensure_changes_table_position_columns(conn)
    return conn
```

- [ ] **Step 4: Add the persistence wiring**

In `backend/app/repository.py`, add the import. Find:
```python
from app.models import Change, ComparisonResult, build_summary
```
Replace with:
```python
from app.models import Change, ComparisonResult, build_summary, TableCoordinate
```

Then find `save_comparison`:

```python
def save_comparison(conn, comparison: ComparisonResult, old_document_id: str, new_document_id: str) -> None:
    conn.execute(
        "INSERT INTO comparisons (id, old_document_id, new_document_id, created_at) VALUES (?, ?, ?, ?)",
        (comparison.comparison_id, old_document_id, new_document_id, datetime.now(timezone.utc).isoformat()),
    )
    for c in comparison.changes:
        conn.execute(
            """INSERT INTO changes
               (id, comparison_id, section, change_type, old_text, new_text, old_page, new_page,
                confidence, ai_risk_level, reviewer_risk_level, reason, reviewer_comment, accepted, source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                c.change_id, comparison.comparison_id, c.section, c.change_type, c.old_text, c.new_text,
                c.old_page, c.new_page, c.confidence, c.ai_risk_level, c.reviewer_risk_level, c.reason,
                c.reviewer_comment, int(c.accepted), c.source,
            ),
        )
    conn.commit()
```

Replace with:

```python
def save_comparison(conn, comparison: ComparisonResult, old_document_id: str, new_document_id: str) -> None:
    conn.execute(
        "INSERT INTO comparisons (id, old_document_id, new_document_id, created_at) VALUES (?, ?, ?, ?)",
        (comparison.comparison_id, old_document_id, new_document_id, datetime.now(timezone.utc).isoformat()),
    )
    for c in comparison.changes:
        old_table_id = c.old_table_position.table_id if c.old_table_position else None
        old_table_row = c.old_table_position.row if c.old_table_position else None
        old_table_col = c.old_table_position.col if c.old_table_position else None
        new_table_id = c.new_table_position.table_id if c.new_table_position else None
        new_table_row = c.new_table_position.row if c.new_table_position else None
        new_table_col = c.new_table_position.col if c.new_table_position else None
        conn.execute(
            """INSERT INTO changes
               (id, comparison_id, section, change_type, old_text, new_text, old_page, new_page,
                confidence, ai_risk_level, reviewer_risk_level, reason, reviewer_comment, accepted, source,
                old_table_id, old_table_row, old_table_col, new_table_id, new_table_row, new_table_col)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                c.change_id, comparison.comparison_id, c.section, c.change_type, c.old_text, c.new_text,
                c.old_page, c.new_page, c.confidence, c.ai_risk_level, c.reviewer_risk_level, c.reason,
                c.reviewer_comment, int(c.accepted), c.source,
                old_table_id, old_table_row, old_table_col, new_table_id, new_table_row, new_table_col,
            ),
        )
    conn.commit()
```

Then find `_row_to_change`:

```python
def _row_to_change(row) -> Change:
    return Change(
        change_id=row["id"], section=row["section"], change_type=row["change_type"],
        old_text=row["old_text"], new_text=row["new_text"], old_page=row["old_page"],
        new_page=row["new_page"], confidence=row["confidence"], ai_risk_level=row["ai_risk_level"],
        reason=row["reason"], reviewer_risk_level=row["reviewer_risk_level"],
        reviewer_comment=row["reviewer_comment"], accepted=bool(row["accepted"]),
        source=row["source"] if row["source"] is not None else "Body",
    )
```

Replace with:

```python
def _row_to_change(row) -> Change:
    old_table_position = (
        TableCoordinate(table_id=row["old_table_id"], row=row["old_table_row"], col=row["old_table_col"])
        if row["old_table_id"] is not None else None
    )
    new_table_position = (
        TableCoordinate(table_id=row["new_table_id"], row=row["new_table_row"], col=row["new_table_col"])
        if row["new_table_id"] is not None else None
    )
    return Change(
        change_id=row["id"], section=row["section"], change_type=row["change_type"],
        old_text=row["old_text"], new_text=row["new_text"], old_page=row["old_page"],
        new_page=row["new_page"], confidence=row["confidence"], ai_risk_level=row["ai_risk_level"],
        reason=row["reason"], reviewer_risk_level=row["reviewer_risk_level"],
        reviewer_comment=row["reviewer_comment"], accepted=bool(row["accepted"]),
        source=row["source"] if row["source"] is not None else "Body",
        old_table_position=old_table_position, new_table_position=new_table_position,
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_repository.py -v`
Expected: PASS, all tests.

- [ ] **Step 6: Verify the migration against the real, live `backend/app.db`**

This file has real rows from actual user testing. Verify the migration is safe before moving on — from `backend/`:

```python
python -c "
from app.db import get_connection
conn = get_connection('app.db')
count_before = conn.execute('SELECT COUNT(*) FROM changes').fetchone()[0]
columns = {row[1] for row in conn.execute('PRAGMA table_info(changes)').fetchall()}
print('row count:', count_before)
print('has new columns:', all(c in columns for c in ['old_table_id', 'old_table_row', 'old_table_col', 'new_table_id', 'new_table_row', 'new_table_col']))
null_count = conn.execute('SELECT COUNT(*) FROM changes WHERE old_table_id IS NULL AND new_table_id IS NULL').fetchone()[0]
print('rows with null table positions (expected: all of them, since this data predates this feature):', null_count)
"
```

Expected: `row count` matches whatever the file currently has, `has new columns` is `True`, and `null_count` equals the total row count (every existing row correctly has `NULL` table positions, since none of them predate this feature having ever computed one). Include this output in your report. Do not modify `app.db` beyond what this read-only-in-effect migration does (it only adds columns, never touches existing data).

- [ ] **Step 7: Commit**

```bash
git add backend/app/db.py backend/app/repository.py backend/tests/test_repository.py
git commit -m "feat: persist table positions to SQLite with migration for existing databases"
```

---

### Task 4: Surface table positions through export and the frontend

**Files:**
- Modify: `backend/app/export.py`
- Modify: `backend/tests/test_export.py`
- Modify: `frontend/logic.py`
- Modify: `frontend/tests/test_logic.py`
- Modify: `frontend/pages/2_Detailed_Changes.py`

**Interfaces:**
- Consumes: `Change.old_table_position`/`new_table_position` from Task 1 (this task's export/frontend tests construct `Change`/dict objects directly, not requiring Tasks 2 or 3).
- Produces: `format_table_cell(old_position: dict | None, new_position: dict | None) -> str` in `frontend/logic.py`. Nothing else in this task is consumed by anything else — it's the last task in the plan.

- [ ] **Step 1: Write the failing tests — backend export**

In `backend/tests/test_export.py`, add `TableCoordinate` to the existing import line. Find:
```python
from app.models import Change, ComparisonResult, build_summary
```
Replace with:
```python
from app.models import Change, ComparisonResult, build_summary, TableCoordinate
```

Append these test functions:

```python
def test_to_json_includes_table_positions_when_present():
    comparison = make_comparison()
    comparison.changes[0].old_table_position = TableCoordinate(table_id=0, row=1, col=1)
    comparison.changes[0].new_table_position = TableCoordinate(table_id=0, row=1, col=1)
    result = to_json(comparison)
    change = result["changes"][0]
    assert change["old_table_position"] == {"table_id": 0, "row": 1, "col": 1}
    assert change["new_table_position"] == {"table_id": 0, "row": 1, "col": 1}


def test_to_json_table_positions_default_to_null():
    result = to_json(make_comparison())
    change = result["changes"][0]
    assert change["old_table_position"] is None
    assert change["new_table_position"] is None


def test_to_csv_table_cell_column_shows_position_when_identical():
    comparison = make_comparison()
    comparison.changes[0].old_table_position = TableCoordinate(table_id=0, row=1, col=1)
    comparison.changes[0].new_table_position = TableCoordinate(table_id=0, row=1, col=1)
    csv_text = to_csv(comparison)
    rows = list(csv.reader(io.StringIO(csv_text)))
    table_cell_index = rows[0].index("table_cell")
    assert rows[1][table_cell_index] == "Table 0, Row 1, Col 1"


def test_to_csv_table_cell_column_shows_arrow_when_positions_differ():
    comparison = make_comparison()
    comparison.changes[0].old_table_position = TableCoordinate(table_id=0, row=1, col=0)
    comparison.changes[0].new_table_position = TableCoordinate(table_id=1, row=0, col=0)
    csv_text = to_csv(comparison)
    rows = list(csv.reader(io.StringIO(csv_text)))
    table_cell_index = rows[0].index("table_cell")
    assert rows[1][table_cell_index] == "Table 0, Row 1, Col 0 -> Table 1, Row 0, Col 0"


def test_to_csv_table_cell_column_shows_only_populated_side():
    comparison = make_comparison()
    comparison.changes[0].old_table_position = None
    comparison.changes[0].new_table_position = TableCoordinate(table_id=1, row=3, col=0)
    csv_text = to_csv(comparison)
    rows = list(csv.reader(io.StringIO(csv_text)))
    table_cell_index = rows[0].index("table_cell")
    assert rows[1][table_cell_index] == "Table 1, Row 3, Col 0"


def test_to_csv_table_cell_column_is_empty_for_body_changes():
    csv_text = to_csv(make_comparison())
    rows = list(csv.reader(io.StringIO(csv_text)))
    table_cell_index = rows[0].index("table_cell")
    assert rows[1][table_cell_index] == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `backend/`): `python -m pytest tests/test_export.py -v`
Expected: the 5 new tests FAIL (`to_json`'s output has no `old_table_position`/`new_table_position` keys yet — `KeyError`; `to_csv`'s header has no `table_cell` column yet — `ValueError` from `.index("table_cell")`). Every pre-existing test still PASSES.

- [ ] **Step 3: Implement the export changes**

In `backend/app/export.py`, find `to_json`:

```python
def to_json(comparison: ComparisonResult) -> dict:
    return {
        "comparison_id": comparison.comparison_id,
        "old_document": comparison.old_document,
        "new_document": comparison.new_document,
        "summary": {
            "total_changes": comparison.summary.total_changes,
            "high_risk": comparison.summary.high_risk,
            "medium_risk": comparison.summary.medium_risk,
            "low_risk": comparison.summary.low_risk,
            "informational": comparison.summary.informational,
        },
        "changes": [
            {
                "change_id": c.change_id,
                "section": c.section,
                "change_type": c.change_type,
                "source": c.source,
                "old_text": c.old_text,
                "new_text": c.new_text,
                "risk_level": _effective_risk(c),
                "ai_risk_level": c.ai_risk_level,
                "reviewer_risk_level": c.reviewer_risk_level,
                "reason": c.reason,
                "old_page": c.old_page,
                "new_page": c.new_page,
                "confidence": c.confidence,
                "reviewer_comment": c.reviewer_comment,
                "accepted": c.accepted,
            }
            for c in comparison.changes
        ],
    }
```

Replace with:

```python
def _table_position_to_dict(position):
    if position is None:
        return None
    return {"table_id": position.table_id, "row": position.row, "col": position.col}


def to_json(comparison: ComparisonResult) -> dict:
    return {
        "comparison_id": comparison.comparison_id,
        "old_document": comparison.old_document,
        "new_document": comparison.new_document,
        "summary": {
            "total_changes": comparison.summary.total_changes,
            "high_risk": comparison.summary.high_risk,
            "medium_risk": comparison.summary.medium_risk,
            "low_risk": comparison.summary.low_risk,
            "informational": comparison.summary.informational,
        },
        "changes": [
            {
                "change_id": c.change_id,
                "section": c.section,
                "change_type": c.change_type,
                "source": c.source,
                "old_text": c.old_text,
                "new_text": c.new_text,
                "risk_level": _effective_risk(c),
                "ai_risk_level": c.ai_risk_level,
                "reviewer_risk_level": c.reviewer_risk_level,
                "reason": c.reason,
                "old_page": c.old_page,
                "new_page": c.new_page,
                "confidence": c.confidence,
                "reviewer_comment": c.reviewer_comment,
                "accepted": c.accepted,
                "old_table_position": _table_position_to_dict(c.old_table_position),
                "new_table_position": _table_position_to_dict(c.new_table_position),
            }
            for c in comparison.changes
        ],
    }
```

Then find `to_csv`:

```python
def to_csv(comparison: ComparisonResult) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "change_id", "section", "change_type", "source", "old_text", "new_text",
        "risk_level", "reason", "old_page", "new_page", "confidence",
        "reviewer_comment", "accepted",
    ])
    for c in comparison.changes:
        writer.writerow([
            c.change_id, c.section, c.change_type, c.source, c.old_text, c.new_text,
            _effective_risk(c), c.reason, c.old_page, c.new_page,
            c.confidence, c.reviewer_comment or "", c.accepted,
        ])
    return output.getvalue()
```

Replace with:

```python
def _format_table_cell(old_position, new_position) -> str:
    if old_position is None and new_position is None:
        return ""
    if old_position is not None and new_position is not None and old_position == new_position:
        return f"Table {old_position.table_id}, Row {old_position.row}, Col {old_position.col}"
    if old_position is not None and new_position is not None:
        return (
            f"Table {old_position.table_id}, Row {old_position.row}, Col {old_position.col} -> "
            f"Table {new_position.table_id}, Row {new_position.row}, Col {new_position.col}"
        )
    position = new_position or old_position
    return f"Table {position.table_id}, Row {position.row}, Col {position.col}"


def to_csv(comparison: ComparisonResult) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "change_id", "section", "change_type", "source", "old_text", "new_text",
        "risk_level", "reason", "old_page", "new_page", "confidence",
        "reviewer_comment", "accepted", "table_cell",
    ])
    for c in comparison.changes:
        writer.writerow([
            c.change_id, c.section, c.change_type, c.source, c.old_text, c.new_text,
            _effective_risk(c), c.reason, c.old_page, c.new_page,
            c.confidence, c.reviewer_comment or "", c.accepted,
            _format_table_cell(c.old_table_position, c.new_table_position),
        ])
    return output.getvalue()
```

(`TableCoordinate.__eq__` is auto-generated by `@dataclass` and compares field values, so `old_position == new_position` correctly compares `table_id`/`row`/`col`, not object identity — no special handling needed.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_export.py -v`
Expected: PASS, all tests.

- [ ] **Step 5: Write the failing tests — frontend**

In `frontend/tests/test_logic.py`, append:

```python
def test_format_table_cell_empty_when_both_positions_are_none():
    assert format_table_cell(None, None) == ""


def test_format_table_cell_shows_position_when_identical():
    position = {"table_id": 0, "row": 1, "col": 1}
    assert format_table_cell(position, position) == "Table 0, Row 1, Col 1"


def test_format_table_cell_shows_arrow_when_positions_differ():
    old_position = {"table_id": 0, "row": 1, "col": 0}
    new_position = {"table_id": 1, "row": 0, "col": 0}
    result = format_table_cell(old_position, new_position)
    assert result == "Table 0, Row 1, Col 0 -> Table 1, Row 0, Col 0"


def test_format_table_cell_shows_only_populated_side():
    new_position = {"table_id": 1, "row": 3, "col": 0}
    assert format_table_cell(None, new_position) == "Table 1, Row 3, Col 0"
```

Also update the top-of-file import. Find:
```python
from logic import filter_changes, build_change_update_payload
```
Replace with:
```python
from logic import filter_changes, build_change_update_payload, format_table_cell
```

- [ ] **Step 6: Run tests to verify they fail**

Run (from `frontend/`): `python -m pytest tests/test_logic.py -v`
Expected: the 4 new tests FAIL with `ImportError` (`format_table_cell` doesn't exist yet). Every pre-existing test still PASSES.

- [ ] **Step 7: Implement the frontend formatting helper**

Append to `frontend/logic.py`:

```python
def format_table_cell(old_position: dict | None, new_position: dict | None) -> str:
    if old_position is None and new_position is None:
        return ""
    if old_position is not None and new_position is not None and old_position == new_position:
        return f"Table {old_position['table_id']}, Row {old_position['row']}, Col {old_position['col']}"
    if old_position is not None and new_position is not None:
        return (
            f"Table {old_position['table_id']}, Row {old_position['row']}, Col {old_position['col']} -> "
            f"Table {new_position['table_id']}, Row {new_position['row']}, Col {new_position['col']}"
        )
    position = new_position or old_position
    return f"Table {position['table_id']}, Row {position['row']}, Col {position['col']}"
```

- [ ] **Step 8: Run tests to verify they pass**

Run (from `frontend/`): `python -m pytest tests/test_logic.py -v`
Expected: PASS, all tests.

- [ ] **Step 9: Wire the new column into the Detailed Changes page**

In `frontend/pages/2_Detailed_Changes.py`, find:

```python
from logic import filter_changes
from bootstrap import ensure_backend_running
```

Replace with:

```python
from logic import filter_changes, format_table_cell
from bootstrap import ensure_backend_running
```

Then find:

```python
    st.table([
        {
            "Section": c["section"],
            "Source": c.get("source", "Body"),
            "Old Text": c["old_text"],
            "New Text": c["new_text"],
            "Change Type": c["change_type"],
            "Risk": c.get("reviewer_risk_level") or c["ai_risk_level"],
            "Reason": c["reason"],
        }
        for c in filtered
    ])
```

Replace with:

```python
    st.table([
        {
            "Section": c["section"],
            "Source": c.get("source", "Body"),
            "Table Cell": format_table_cell(c.get("old_table_position"), c.get("new_table_position")),
            "Old Text": c["old_text"],
            "New Text": c["new_text"],
            "Change Type": c["change_type"],
            "Risk": c.get("reviewer_risk_level") or c["ai_risk_level"],
            "Reason": c["reason"],
        }
        for c in filtered
    ])
```

(Uses `.get(...)` defensively, not a hard index — the same defensive pattern already used for `"source"` in this exact table, since `st.session_state["comparison"]` can carry a payload from a not-yet-restarted older backend build that predates this field, as has genuinely happened earlier in this project's history.)

- [ ] **Step 10: Run the frontend test suite**

Run (from `frontend/`): `python -m pytest -v`
Expected: PASS, all tests, including the pre-existing `test_page_loads_with_a_comparison` (its fixture change dict has no `old_table_position`/`new_table_position` keys at all, so `.get(...)` correctly returns `None` for both and `format_table_cell(None, None)` correctly returns `""` — no exception).

- [ ] **Step 11: Run the full backend suite**

Run (from `backend/`): `python -m pytest -v`
Expected: PASS, all tests, no regressions anywhere else in the suite.

- [ ] **Step 12: Commit**

```bash
git add backend/app/export.py backend/tests/test_export.py frontend/logic.py frontend/tests/test_logic.py frontend/pages/2_Detailed_Changes.py
git commit -m "feat: surface table cell position through export and the Detailed Changes table"
```
