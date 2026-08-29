# Structural Change Summary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show six section-level structural counts — added, deleted, renamed, renumbered, cascaded, moved — on the Change Summary page and in the JSON export.

**Architecture:** `ComparisonSummary` gains six defaulted `int` fields that `build_summary` derives by counting `change_type` equality. The summary is computed, never stored, so both a fresh comparison and one reloaded from SQLite get them with no migration. `export.py` names summary keys explicitly, so the six are added there. The Change Summary page renders a second `st.metric` row.

**Tech Stack:** Python 3.14, Streamlit 1.60, pytest.

## Global Constraints

- Never read or write `backend/app.db` — it is the user's real database.
- **No schema change and no migration.** The summary is derived by `build_summary(changes)` in both `pipeline.py` and `repository.py`.
- **Match `change_type` by equality, never by prefix.** `section_renumbered_cascade` starts with `section_renumbered`.
- Several files in this tree carry the user's uncommitted work. Stage files by name. **Never `git add -A`, never `git commit -a`.** If you cannot stage a file, **STOP and report** — never reconstruct a file from HEAD.
- Backend is green at 348 tests and frontend at 82 before this work starts.

## Prior verification

The whole change was prototyped against live code and reverted before this plan was written. The code below is the code that ran.

- **Backend change broke nothing** — 348 still passed with the six fields and six export keys added. No test constructs `ComparisonSummary` directly.
- **The page crashes with `KeyError` if the summary lacks the new keys.** Indexing `summary["sections_added"]` took the whole page down against a fixture without them. This is the same failure mode a previous final review caught in `table_group_key`. The page therefore uses `.get(name, 0)`.
- **Corpus cross-check passed on all 11 pairs** — each count re-derived from the raw change list matched.
- **`SOP` is the case that proves the moved rule**: it has one `moved_paragraph` and reports `sections_moved=0`.
- `section_renumbered_cascade` occurs in **no** corpus document, so `sections_cascaded` is 0 everywhere. Its correctness is provable only by unit test.

## File Structure

- `backend/app/models.py` — six fields on `ComparisonSummary`, six counts in `build_summary`.
- `backend/app/export.py` — six keys in the summary dict.
- `frontend/pages/1_Change_Summary.py` — a subheader and six metrics.
- `backend/tests/test_models.py`, `backend/tests/test_export.py`, `frontend/tests/test_page_change_summary.py` — new tests.

---

### Task 1: Derive the six structural counts

**Files:**
- Modify: `backend/app/models.py`
- Test: `backend/tests/test_models.py`

**Interfaces:**
- Produces: `ComparisonSummary.sections_added`, `.sections_deleted`, `.sections_renamed`, `.sections_renumbered`, `.sections_cascaded`, `.sections_moved` — all `int`, defaulting to `0`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_models.py`:

```python
def test_build_summary_counts_structural_changes():
    changes = [
        Change("1", "s", "section_added", "", "n", None, None, 1.0, "High", "r"),
        Change("2", "s", "section_added", "", "n", None, None, 1.0, "High", "r"),
        Change("3", "s", "section_deleted", "o", "", None, None, 1.0, "High", "r"),
        Change("4", "s", "section_heading_changed", "o", "n", None, None, 1.0, "Medium", "r"),
        Change("5", "s", "section_renumbered", "o", "n", None, None, 1.0, "Informational", "r"),
        Change("6", "s", "section_reordered", "o", "n", None, None, 1.0, "Informational", "r"),
        Change("7", "s", "numeric_change", "95%", "98%", None, None, 1.0, "High", "r"),
    ]

    summary = build_summary(changes)

    assert summary.sections_added == 2
    assert summary.sections_deleted == 1
    assert summary.sections_renamed == 1
    assert summary.sections_renumbered == 1
    assert summary.sections_moved == 1
    assert summary.sections_cascaded == 0


def test_build_summary_does_not_count_a_cascade_as_a_deliberate_renumber():
    # "section_renumbered_cascade" starts with "section_renumbered", so a prefix
    # match would count every cascade in BOTH metrics - inflating the exact number
    # the split exists to clarify. This is the single most likely implementation
    # error, and no corpus document exercises the cascade path.
    changes = [
        Change("1", "s", "section_renumbered_cascade", "o", "n", None, None, 1.0, "Informational", "r"),
        Change("2", "s", "section_renumbered_cascade", "o", "n", None, None, 1.0, "Informational", "r"),
    ]

    summary = build_summary(changes)

    assert summary.sections_cascaded == 2
    assert summary.sections_renumbered == 0


def test_build_summary_does_not_count_content_moves_as_moved_sections():
    # Content moving BETWEEN sections is not a section moving. The real SOP pair
    # has one moved_paragraph and no section_reordered; counting it here would
    # report a relocated section for a document in which none moved.
    changes = [
        Change("1", "s", "moved_paragraph", "o", "n", None, None, 1.0, "Informational", "r"),
        Change("2", "s", "moved_table_content", "o", "n", None, None, 1.0, "Informational", "r"),
    ]

    summary = build_summary(changes)

    assert summary.sections_moved == 0


def test_build_summary_reports_zero_structural_counts_when_there_are_none():
    changes = [Change("1", "s", "numeric_change", "95%", "98%", None, None, 1.0, "High", "r")]

    summary = build_summary(changes)

    assert summary.sections_added == 0
    assert summary.sections_deleted == 0
    assert summary.sections_renamed == 0
    assert summary.sections_renumbered == 0
    assert summary.sections_cascaded == 0
    assert summary.sections_moved == 0
```

`Change`'s positional order is `(change_id, section, change_type, old_text, new_text, old_page, new_page, confidence, ai_risk_level, reason)` — this matches the construction style already used by `test_build_summary_counts_by_risk` in this file.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_models.py -k structural -v`
Expected: FAIL — `AttributeError: 'ComparisonSummary' object has no attribute 'sections_added'`.

- [ ] **Step 3: Add the six fields**

In `backend/app/models.py`, extend `ComparisonSummary`:

```python
class ComparisonSummary:
    total_changes: int
    high_risk: int
    medium_risk: int
    low_risk: int
    informational: int
    sections_added: int = 0
    sections_deleted: int = 0
    sections_renamed: int = 0
    sections_renumbered: int = 0
    sections_cascaded: int = 0
    sections_moved: int = 0
```

Defaults so every existing construction site keeps working, the same way
`TableCoordinate` gained its span fields.

- [ ] **Step 4: Derive them in `build_summary`**

Extend the existing return, after the `informational=` line:

```python
        informational=sum(1 for c in changes if c.ai_risk_level == "Informational"),
        # Match change_type by EQUALITY, never by prefix. "section_renumbered_cascade"
        # starts with "section_renumbered", so a startswith check would count every
        # cascade in both metrics - inflating the exact number the split exists to
        # clarify. sections_moved is section_reordered only: moved_paragraph and
        # moved_table_content are content moving BETWEEN sections, and counting them
        # here would report a moved section for a document where none moved.
        sections_added=sum(1 for c in changes if c.change_type == "section_added"),
        sections_deleted=sum(1 for c in changes if c.change_type == "section_deleted"),
        sections_renamed=sum(1 for c in changes if c.change_type == "section_heading_changed"),
        sections_renumbered=sum(1 for c in changes if c.change_type == "section_renumbered"),
        sections_cascaded=sum(1 for c in changes if c.change_type == "section_renumbered_cascade"),
        sections_moved=sum(1 for c in changes if c.change_type == "section_reordered"),
    )
```

- [ ] **Step 5: Run the tests**

Run: `cd backend && python -m pytest tests/test_models.py -q`
Expected: PASS.

- [ ] **Step 6: Run the full backend suite**

Run: `cd backend && python -m pytest -q`
Expected: 352 pass. Verified in prototyping: no existing test breaks.

- [ ] **Step 7: Commit**

```bash
git add backend/app/models.py backend/tests/test_models.py
git commit -m "feat: derive section-level structural counts in the comparison summary"
```

---

### Task 2: Carry the counts into the JSON export

**Files:**
- Modify: `backend/app/export.py`
- Test: `backend/tests/test_export.py`

**Interfaces:**
- Consumes: the six `ComparisonSummary` fields from Task 1.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_export.py`, following the file's existing
construction of a `ComparisonResult`:

This file constructs `Change` with keyword arguments — match that style here
(`test_models.py` uses positional; each file keeps its own convention).
`to_json`, `build_summary`, `Change`, and `ComparisonResult` are all already
imported at the top of this file.

```python
def test_to_json_includes_structural_counts():
    changes = [
        Change(
            change_id="ch-1", section="9.0 Training", change_type="section_added",
            old_text="", new_text="9.0 Training", old_page=None, new_page=None,
            confidence=1.0, ai_risk_level="High", reason="Section added.",
        ),
        Change(
            change_id="ch-2", section="4.0 Approval", change_type="section_reordered",
            old_text="4.0 Approval", new_text="4.0 Approval", old_page=None, new_page=None,
            confidence=0.86, ai_risk_level="Informational", reason="Section moved.",
        ),
    ]
    comparison = ComparisonResult(
        comparison_id="CMP-002", old_document="v1.docx", new_document="v2.docx",
        summary=build_summary(changes), changes=changes,
    )

    result = to_json(comparison)

    assert result["summary"]["sections_added"] == 1
    assert result["summary"]["sections_moved"] == 1
    assert result["summary"]["sections_cascaded"] == 0
```

Note `test_to_json_matches_expected_schema_shape` in this file does **not**
assert exact key equality on the summary dict — confirmed in prototyping,
where adding all six keys left the whole suite green.

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && python -m pytest tests/test_export.py -k structural -v`
Expected: FAIL — `KeyError: 'sections_added'`.

- [ ] **Step 3: Add the six keys**

In `backend/app/export.py`, extend the `"summary"` dict after
`"informational"`:

```python
            "informational": comparison.summary.informational,
            "sections_added": comparison.summary.sections_added,
            "sections_deleted": comparison.summary.sections_deleted,
            "sections_renamed": comparison.summary.sections_renamed,
            "sections_renumbered": comparison.summary.sections_renumbered,
            "sections_cascaded": comparison.summary.sections_cascaded,
            "sections_moved": comparison.summary.sections_moved,
        },
```

The CSV export is per-change and needs no change.

- [ ] **Step 4: Run the full backend suite**

Run: `cd backend && python -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/export.py backend/tests/test_export.py
git commit -m "feat: include structural counts in the JSON export"
```

---

### Task 3: Show the structural metric row

**Files:**
- Modify: `frontend/pages/1_Change_Summary.py`
- Test: `frontend/tests/test_page_change_summary.py`

- [ ] **Step 1: Write the failing tests**

Append to `frontend/tests/test_page_change_summary.py`, following the
existing `AppTest` pattern in that file:

```python
def test_page_shows_structural_metrics():
    with patch("bootstrap._backend_is_reachable", return_value=True):
        at = AppTest.from_file("pages/1_Change_Summary.py")
        at.session_state["comparison"] = {
            "summary": {
                "total_changes": 6, "high_risk": 3, "medium_risk": 1,
                "low_risk": 0, "informational": 2,
                "sections_added": 2, "sections_deleted": 1, "sections_renamed": 1,
                "sections_renumbered": 1, "sections_cascaded": 0, "sections_moved": 1,
            }
        }
        at.run()

    assert not at.exception
    labels = [m.label for m in at.metric]
    assert "Sections Moved" in labels
    assert "Sections Cascaded" in labels


def test_page_survives_a_summary_without_structural_counts():
    # Indexing these keys took the whole page down with a KeyError against a
    # summary produced before the fields existed - the same failure mode a prior
    # review found in the Detailed Changes table renderer.
    with patch("bootstrap._backend_is_reachable", return_value=True):
        at = AppTest.from_file("pages/1_Change_Summary.py")
        at.session_state["comparison"] = {
            "summary": {"total_changes": 3, "high_risk": 2, "medium_risk": 1,
                        "low_risk": 0, "informational": 0}
        }
        at.run()

    assert not at.exception
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd frontend && python -m pytest tests/test_page_change_summary.py -v`
Expected: `test_page_shows_structural_metrics` FAILS — the labels do not exist.

- [ ] **Step 3: Add the subheader and six metrics**

In `frontend/pages/1_Change_Summary.py`, after the existing
`col5.metric("Informational", ...)` line:

```python
    st.subheader("Structural Changes")
    # .get with a default so a summary produced before these fields existed
    # renders as zeros instead of taking the whole page down with a KeyError.
    # Every label is prefixed "Sections" because the report below also contains
    # moved paragraphs, moved table content, and added/deleted table rows - a bare
    # "Moved" would be read against any of those. The Cascaded tooltip is required,
    # not decorative: the word is not self-explanatory.
    s1, s2, s3, s4, s5, s6 = st.columns(6)
    s1.metric("Sections Added", summary.get("sections_added", 0),
              help="A section present in the new document only.")
    s2.metric("Sections Deleted", summary.get("sections_deleted", 0),
              help="A section present in the old document only.")
    s3.metric("Sections Renamed", summary.get("sections_renamed", 0),
              help="Heading wording changed.")
    s4.metric("Sections Renumbered", summary.get("sections_renumbered", 0),
              help="Section number changed deliberately.")
    s5.metric("Sections Cascaded", summary.get("sections_cascaded", 0),
              help="Number shifted only because a section above was added or "
                   "removed; wording unchanged.")
    s6.metric("Sections Moved", summary.get("sections_moved", 0),
              help="Section changed position in the document.")
```

- [ ] **Step 4: Run both suites**

Run: `cd frontend && python -m pytest -q` and `cd backend && python -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Corpus cross-check**

Run every DOCX pair in `test-documents/docx/` through
`pipeline.compare_documents` with `llm_classifier.classify_changes_batch`
stubbed, and assert each summary count equals the count re-derived directly
from that comparison's change list. Confirm `SOP` reports
`sections_moved == 0` despite containing a `moved_paragraph`.

- [ ] **Step 6: Commit**

```bash
git add frontend/pages/1_Change_Summary.py frontend/tests/test_page_change_summary.py
git commit -m "feat: show a structural change summary on the Change Summary page"
```
