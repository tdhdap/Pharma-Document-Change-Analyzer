# Detailed Changes UI Reorganization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Detailed Changes page's single flat table with four collapsible top-level groups (Headers, Footers, Body, Tables, always in that order), each nested one level further by document section, with a risk-badge header on every group so a reviewer can scan for urgency without opening everything.

**Architecture:** New pure grouping/formatting helpers in `frontend/logic.py` (category assignment, per-section grouping, risk-count badge formatting, table-coordinate formatting) — all independently unit-testable with plain dicts, no Streamlit involved. `frontend/pages/2_Detailed_Changes.py` is rewritten to call these helpers and render nested `st.expander`s (confirmed empirically that Streamlit 1.60.0 permits nesting them, contrary to older-version behavior) plus `st.table` for the leaf rows.

**Tech Stack:** Python, Streamlit 1.60.0, `streamlit.testing.v1.AppTest` for page-level tests, pytest.

## Global Constraints

- Four top-level groups, always in this fixed order: Headers, Footers, Body, Tables — always rendered, even at 0 changes (never hidden). (spec: "Decision")
- Category assignment order: `source == "Table"` is checked **first** (before header/footer prefix checks) — a table inside a header/footer must land in "Tables", not "Headers"/"Footers". (spec: "Category assignment")
- Headers/Footers = `section` starts with `"Page Header"` / `"Page Footer"` respectively. Body = everything else that isn't a table change (regular numbered sections, `"Text Box N"`, `"Footnote N"`). (spec: "Category assignment")
- Headers/Footers render their changes directly (no further nesting). Body/Tables each break down one level further into one sub-group per originating document section, in document order (first-seen order across the input change list). (spec: "Nesting")
- Every group/section header shows: one leading emoji for the highest-severity risk tier present (🔴 High, 🟡 Medium, 🟢 Low, ⚪ Informational), the name, the total count, and a parenthetical breakdown of every present tier with its count, e.g. `"🔴 4.0 Procedure — 5 changes (3 High, 2 Medium)"`. A group/section with zero changes shows `"{name} — 0 changes"` with no emoji. (spec: "Section/category header format")
- A group/section defaults to expanded if it contains at least one High-risk change; otherwise it defaults collapsed. (spec: "Section/category header format")
- Body-style tables (Headers, Footers, each Body sub-group) show columns: Old Text, New Text, Change Type, Risk, Reason. No Source or Table Cell column. (spec: "Columns")
- Table-style tables (each Tables sub-group) show columns: Table ID, Row, Col, Old Text, New Text, Change Type, Risk, Reason. Each of Table ID/Row/Col independently shows `"{old} → {new}"` only when that specific field differs between old and new position; otherwise the single value. When only one side is present (added/deleted cell), show that side's values plainly. (spec: "Columns")
- The existing risk/section/change-type filters (`st.selectbox`, `filter_changes()`) are applied to the flat change list *before* grouping — unchanged behavior, just applied earlier in the pipeline. (spec: "Filters")
- Risk level for display/counting purposes is always `change.get("reviewer_risk_level") or change["ai_risk_level"]` — the same resolution rule `filter_changes` already uses. (spec: "Testing", mirrors existing `filter_changes` behavior)

---

### Task 1: Grouping and formatting helpers in `logic.py`

**Files:**
- Modify: `frontend/logic.py`
- Test: `frontend/tests/test_logic.py`

**Interfaces:**
- Produces: `categorize_change(change: dict) -> str` — returns one of `"Headers"`, `"Footers"`, `"Body"`, `"Tables"`.
- Produces: `group_changes_for_display(changes: list[dict]) -> dict` — returns `{"Headers": list[dict], "Footers": list[dict], "Body": dict[str, list[dict]], "Tables": dict[str, list[dict]]}`. Headers/Footers map directly to a flat list of changes (possibly empty). Body/Tables map section name to that section's list of changes, with sections in first-seen order; the dict itself is empty when the category has no changes.
- Produces: `compute_risk_counts(changes: list[dict]) -> dict` — returns risk tier (`"High"`/`"Medium"`/`"Low"`/`"Informational"`) mapped to count, only including tiers present, ordered High→Medium→Low→Informational (relies on Python's dict insertion-order guarantee).
- Produces: `format_group_label(name: str, changes: list[dict]) -> str` — the full header string described in Global Constraints.
- Produces: `has_high_risk(changes: list[dict]) -> bool`.
- Produces: `format_table_coordinates(old_position: dict | None, new_position: dict | None) -> tuple[str, str, str]` — returns `(table_id_str, row_str, col_str)`, each independently arrow-formatted per Global Constraints. `old_position`/`new_position` are `{"table_id": int, "row": int, "col": int}` or `None`, matching the shape already used by the existing `format_table_cell`.
- Consumes: nothing new from other tasks — this task is self-contained.

- [ ] **Step 1: Write the failing tests for `categorize_change`**

In `frontend/tests/test_logic.py`, add to the existing `from logic import ...` line (turn it into a second import line, don't merge — matches this file's existing style of one import per feature area... actually this file currently has a single `from logic import filter_changes, build_change_update_payload, format_table_cell` line; extend that same line since these are all "logic" imports used throughout the same test file):

```python
from logic import (
    filter_changes, build_change_update_payload, format_table_cell,
    categorize_change, group_changes_for_display, compute_risk_counts,
    format_group_label, has_high_risk, format_table_coordinates,
)
```

Add these tests (append to the end of the file):

```python
def test_categorize_change_page_header_is_headers():
    change = {"section": "Page Header", "source": "Body"}
    assert categorize_change(change) == "Headers"


def test_categorize_change_qualified_page_header_is_headers():
    change = {"section": "Page Header (Section 2, First Page)", "source": "Body"}
    assert categorize_change(change) == "Headers"


def test_categorize_change_page_footer_is_footers():
    change = {"section": "Page Footer", "source": "Body"}
    assert categorize_change(change) == "Footers"


def test_categorize_change_table_source_is_tables_even_for_regular_section():
    change = {"section": "4.0 Procedure", "source": "Table"}
    assert categorize_change(change) == "Tables"


def test_categorize_change_table_source_is_tables_even_for_text_box():
    change = {"section": "Text Box 1", "source": "Table"}
    assert categorize_change(change) == "Tables"


def test_categorize_change_table_source_is_tables_even_for_page_header():
    # Proves the check order from the plan's Global Constraints: source=="Table"
    # is checked BEFORE the header/footer prefix check, so a table inside a
    # header still lands in "Tables", not "Headers".
    change = {"section": "Page Header", "source": "Table"}
    assert categorize_change(change) == "Tables"


def test_categorize_change_body_sourced_regular_section_is_body():
    change = {"section": "4.0 Procedure", "source": "Body"}
    assert categorize_change(change) == "Body"


def test_categorize_change_text_box_is_body():
    change = {"section": "Text Box 1", "source": "Body"}
    assert categorize_change(change) == "Body"


def test_categorize_change_footnote_is_body():
    change = {"section": "Footnote 1", "source": "Body"}
    assert categorize_change(change) == "Body"


def test_categorize_change_defaults_source_to_body_when_absent():
    # Change.source always exists on real API responses, but categorize_change
    # should not crash on a dict missing it.
    change = {"section": "4.0 Procedure"}
    assert categorize_change(change) == "Body"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && python -m pytest tests/test_logic.py -k categorize -v`
Expected: FAIL with `ImportError: cannot import name 'categorize_change'`.

- [ ] **Step 3: Implement `categorize_change`**

In `frontend/logic.py`, add at the end of the file:

```python
def categorize_change(change: dict) -> str:
    if change.get("source", "Body") == "Table":
        return "Tables"
    section = change["section"]
    if section.startswith("Page Header"):
        return "Headers"
    if section.startswith("Page Footer"):
        return "Footers"
    return "Body"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd frontend && python -m pytest tests/test_logic.py -k categorize -v`
Expected: 10 passed.

- [ ] **Step 5: Write the failing tests for `group_changes_for_display`**

Append to `frontend/tests/test_logic.py`:

```python
def test_group_changes_for_display_all_four_keys_always_present():
    result = group_changes_for_display([])
    assert set(result.keys()) == {"Headers", "Footers", "Body", "Tables"}
    assert result["Headers"] == []
    assert result["Footers"] == []
    assert result["Body"] == {}
    assert result["Tables"] == {}


def test_group_changes_for_display_sorts_into_correct_categories():
    changes = [
        {"change_id": "h1", "section": "Page Header", "source": "Body"},
        {"change_id": "f1", "section": "Page Footer", "source": "Body"},
        {"change_id": "b1", "section": "2.0 Scope", "source": "Body"},
        {"change_id": "t1", "section": "4.0 Procedure", "source": "Table"},
    ]
    result = group_changes_for_display(changes)
    assert [c["change_id"] for c in result["Headers"]] == ["h1"]
    assert [c["change_id"] for c in result["Footers"]] == ["f1"]
    assert [c["change_id"] for c in result["Body"]["2.0 Scope"]] == ["b1"]
    assert [c["change_id"] for c in result["Tables"]["4.0 Procedure"]] == ["t1"]


def test_group_changes_for_display_sections_in_first_seen_order():
    changes = [
        {"change_id": "1", "section": "8.0 Training Requirements", "source": "Body"},
        {"change_id": "2", "section": "2.0 Scope", "source": "Body"},
        {"change_id": "3", "section": "8.0 Training Requirements", "source": "Body"},
    ]
    result = group_changes_for_display(changes)
    assert list(result["Body"].keys()) == ["8.0 Training Requirements", "2.0 Scope"]
    assert [c["change_id"] for c in result["Body"]["8.0 Training Requirements"]] == ["1", "3"]


def test_group_changes_for_display_multiple_table_sections_kept_separate():
    changes = [
        {"change_id": "1", "section": "4.0 Procedure", "source": "Table"},
        {"change_id": "2", "section": "5.0 In-Process Controls", "source": "Table"},
    ]
    result = group_changes_for_display(changes)
    assert list(result["Tables"].keys()) == ["4.0 Procedure", "5.0 In-Process Controls"]
```

- [ ] **Step 6: Run the tests to verify they fail**

Run: `cd frontend && python -m pytest tests/test_logic.py -k group_changes_for_display -v`
Expected: FAIL with `ImportError: cannot import name 'group_changes_for_display'`.

- [ ] **Step 7: Implement `group_changes_for_display`**

Append to `frontend/logic.py`:

```python
def group_changes_for_display(changes: list[dict]) -> dict:
    result = {"Headers": [], "Footers": [], "Body": {}, "Tables": {}}
    for change in changes:
        category = categorize_change(change)
        if category in ("Headers", "Footers"):
            result[category].append(change)
        else:
            result[category].setdefault(change["section"], []).append(change)
    return result
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `cd frontend && python -m pytest tests/test_logic.py -k group_changes_for_display -v`
Expected: 4 passed.

- [ ] **Step 9: Write the failing tests for `compute_risk_counts`, `format_group_label`, and `has_high_risk`**

Append to `frontend/tests/test_logic.py`:

```python
def test_compute_risk_counts_empty_for_no_changes():
    assert compute_risk_counts([]) == {}


def test_compute_risk_counts_counts_and_orders_by_severity():
    changes = [
        {"ai_risk_level": "Low", "reviewer_risk_level": None},
        {"ai_risk_level": "High", "reviewer_risk_level": None},
        {"ai_risk_level": "High", "reviewer_risk_level": None},
        {"ai_risk_level": "Medium", "reviewer_risk_level": None},
    ]
    result = compute_risk_counts(changes)
    assert list(result.items()) == [("High", 2), ("Medium", 1), ("Low", 1)]


def test_compute_risk_counts_uses_reviewer_override():
    changes = [{"ai_risk_level": "High", "reviewer_risk_level": "Low"}]
    assert compute_risk_counts(changes) == {"Low": 1}


def test_format_group_label_zero_changes():
    assert format_group_label("Footers", []) == "Footers — 0 changes"


def test_format_group_label_single_tier_singular():
    changes = [{"ai_risk_level": "Informational", "reviewer_risk_level": None}]
    result = format_group_label("6.0 Quality Control Release", changes)
    assert result == "⚪ 6.0 Quality Control Release — 1 change (1 Informational)"


def test_format_group_label_mixed_tiers_uses_highest_severity_emoji():
    changes = [
        {"ai_risk_level": "High", "reviewer_risk_level": None},
        {"ai_risk_level": "High", "reviewer_risk_level": None},
        {"ai_risk_level": "High", "reviewer_risk_level": None},
        {"ai_risk_level": "Medium", "reviewer_risk_level": None},
        {"ai_risk_level": "Medium", "reviewer_risk_level": None},
    ]
    result = format_group_label("4.0 Procedure", changes)
    assert result == "\U0001f534 4.0 Procedure — 5 changes (3 High, 2 Medium)"


def test_has_high_risk_true_when_present():
    changes = [{"ai_risk_level": "Low", "reviewer_risk_level": None}, {"ai_risk_level": "High", "reviewer_risk_level": None}]
    assert has_high_risk(changes) is True


def test_has_high_risk_false_when_absent():
    changes = [{"ai_risk_level": "Low", "reviewer_risk_level": None}, {"ai_risk_level": "Medium", "reviewer_risk_level": None}]
    assert has_high_risk(changes) is False


def test_has_high_risk_false_for_empty_list():
    assert has_high_risk([]) is False


def test_has_high_risk_respects_reviewer_override_downgrade():
    changes = [{"ai_risk_level": "High", "reviewer_risk_level": "Low"}]
    assert has_high_risk(changes) is False
```

- [ ] **Step 10: Run the tests to verify they fail**

Run: `cd frontend && python -m pytest tests/test_logic.py -k "compute_risk_counts or format_group_label or has_high_risk" -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 11: Implement `compute_risk_counts`, `format_group_label`, and `has_high_risk`**

Append to `frontend/logic.py`:

```python
_RISK_SEVERITY_ORDER = ["High", "Medium", "Low", "Informational"]
_RISK_EMOJI = {"High": "\U0001f534", "Medium": "\U0001f7e1", "Low": "\U0001f7e2", "Informational": "⚪"}


def _change_risk(change: dict) -> str:
    return change.get("reviewer_risk_level") or change["ai_risk_level"]


def compute_risk_counts(changes: list[dict]) -> dict:
    counts = {}
    for change in changes:
        risk = _change_risk(change)
        counts[risk] = counts.get(risk, 0) + 1
    return {level: counts[level] for level in _RISK_SEVERITY_ORDER if level in counts}


def format_group_label(name: str, changes: list[dict]) -> str:
    total = len(changes)
    risk_counts = compute_risk_counts(changes)
    if not risk_counts:
        return f"{name} — 0 changes"
    top_tier = next(iter(risk_counts))
    emoji = _RISK_EMOJI[top_tier]
    breakdown = ", ".join(f"{count} {level}" for level, count in risk_counts.items())
    plural = "" if total == 1 else "s"
    return f"{emoji} {name} — {total} change{plural} ({breakdown})"


def has_high_risk(changes: list[dict]) -> bool:
    return any(_change_risk(c) == "High" for c in changes)
```

- [ ] **Step 12: Run the tests to verify they pass**

Run: `cd frontend && python -m pytest tests/test_logic.py -k "compute_risk_counts or format_group_label or has_high_risk" -v`
Expected: 10 passed.

- [ ] **Step 13: Write the failing tests for `format_table_coordinates`**

Append to `frontend/tests/test_logic.py`:

```python
def test_format_table_coordinates_both_none():
    assert format_table_coordinates(None, None) == ("", "", "")


def test_format_table_coordinates_identical_positions():
    position = {"table_id": 0, "row": 1, "col": 2}
    assert format_table_coordinates(position, position) == ("0", "1", "2")


def test_format_table_coordinates_only_new_present():
    new_position = {"table_id": 0, "row": 3, "col": 0}
    assert format_table_coordinates(None, new_position) == ("0", "3", "0")


def test_format_table_coordinates_only_old_present():
    old_position = {"table_id": 0, "row": 2, "col": 1}
    assert format_table_coordinates(old_position, None) == ("0", "2", "1")


def test_format_table_coordinates_row_moved_col_same():
    old_position = {"table_id": 0, "row": 1, "col": 0}
    new_position = {"table_id": 0, "row": 3, "col": 0}
    assert format_table_coordinates(old_position, new_position) == ("0", "1 → 3", "0")


def test_format_table_coordinates_table_id_and_col_moved_row_same():
    old_position = {"table_id": 0, "row": 1, "col": 0}
    new_position = {"table_id": 1, "row": 1, "col": 2}
    assert format_table_coordinates(old_position, new_position) == ("0 → 1", "1", "0 → 2")
```

- [ ] **Step 14: Run the tests to verify they fail**

Run: `cd frontend && python -m pytest tests/test_logic.py -k format_table_coordinates -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 15: Implement `format_table_coordinates`**

Append to `frontend/logic.py`:

```python
def format_table_coordinates(old_position: dict | None, new_position: dict | None) -> tuple[str, str, str]:
    if old_position is None and new_position is None:
        return "", "", ""

    def field(key: str) -> str:
        if old_position is not None and new_position is not None and old_position[key] != new_position[key]:
            return f"{old_position[key]} → {new_position[key]}"
        source = new_position if new_position is not None else old_position
        return str(source[key])

    return field("table_id"), field("row"), field("col")
```

- [ ] **Step 16: Run the tests to verify they pass**

Run: `cd frontend && python -m pytest tests/test_logic.py -k format_table_coordinates -v`
Expected: 6 passed.

- [ ] **Step 17: Run the full frontend suite**

Run: `cd frontend && python -m pytest -q`
Expected: all tests pass. (Count depends on the existing suite size; no failures, no regressions in the pre-existing tests in this file.)

- [ ] **Step 18: Commit**

```bash
git add frontend/logic.py frontend/tests/test_logic.py
git commit -m "feat: add grouping and formatting helpers for Detailed Changes UI reorg"
```

---

### Task 2: Rewrite the Detailed Changes page to use the grouped structure

**Files:**
- Modify: `frontend/pages/2_Detailed_Changes.py`
- Test: `frontend/tests/test_page_detailed_changes.py`

**Interfaces:**
- Consumes (from Task 1, `frontend/logic.py`): `filter_changes` (existing, unchanged signature), `group_changes_for_display(changes: list[dict]) -> dict`, `format_group_label(name: str, changes: list[dict]) -> str`, `has_high_risk(changes: list[dict]) -> bool`, `format_table_coordinates(old_position, new_position) -> tuple[str, str, str]`.
- Produces: the rewritten page itself — no other task depends on this one.

Streamlit 1.60.0 permits nesting `st.expander` inside another `st.expander` (verified empirically before writing this plan — this contradicts older Streamlit versions' restriction, so don't assume it's disallowed).

- [ ] **Step 1: Write the failing page-level tests**

Read the current `frontend/tests/test_page_detailed_changes.py` first — it has two existing tests (`test_page_loads_with_no_comparison`, `test_page_loads_with_a_comparison`) using the `streamlit.testing.v1.AppTest` pattern with `unittest.mock.patch("bootstrap._backend_is_reachable", return_value=True)`. Keep both of those exactly as they are (they test the empty-comparison and minimal-comparison cases, which still apply), and append these new tests to the same file:

```python
def _make_comparison(changes):
    return {"changes": changes}


def _run_page_with(changes):
    with patch("bootstrap._backend_is_reachable", return_value=True):
        at = AppTest.from_file("pages/2_Detailed_Changes.py")
        at.session_state["comparison"] = _make_comparison(changes)
        at.run()
    return at


_ALL_CATEGORY_CHANGES = [
    {
        "change_id": "h1", "section": "Page Header", "source": "Body", "change_type": "section_added",
        "old_text": "", "new_text": "Confidential", "ai_risk_level": "High",
        "reviewer_risk_level": None, "reason": "new header",
    },
    {
        "change_id": "b1", "section": "2.0 Scope", "source": "Body", "change_type": "section_heading_changed",
        "old_text": "2.0 Scope", "new_text": "2.0 Applicability", "ai_risk_level": "Medium",
        "reviewer_risk_level": None, "reason": "heading changed",
    },
    {
        "change_id": "t1", "section": "4.0 Procedure", "source": "Table", "change_type": "numeric_change",
        "old_text": "14.8 kN", "new_text": "15.1 kN", "ai_risk_level": "High",
        "reviewer_risk_level": None, "reason": "value changed",
        "old_table_position": {"table_id": 0, "row": 1, "col": 2},
        "new_table_position": {"table_id": 0, "row": 1, "col": 2},
    },
]


def test_page_renders_four_categories_in_order():
    at = _run_page_with(_ALL_CATEGORY_CHANGES)
    assert not at.exception
    labels = [e.label for e in at.expander]
    header_index = next(i for i, l in enumerate(labels) if "Headers" in l)
    footer_index = next(i for i, l in enumerate(labels) if "Footers" in l)
    body_index = next(i for i, l in enumerate(labels) if "Body" in l)
    tables_index = next(i for i, l in enumerate(labels) if "Tables" in l)
    assert header_index < footer_index < body_index < tables_index


def test_page_shows_all_four_categories_even_when_some_are_empty():
    # Only a Body change - Headers, Footers, and Tables must still render, showing 0 changes.
    at = _run_page_with([_ALL_CATEGORY_CHANGES[1]])
    assert not at.exception
    labels = [e.label for e in at.expander]
    assert any(l == "Headers — 0 changes" for l in labels)
    assert any(l == "Footers — 0 changes" for l in labels)
    assert any(l == "Tables — 0 changes" for l in labels)


def test_page_nests_body_and_tables_by_section():
    at = _run_page_with(_ALL_CATEGORY_CHANGES)
    assert not at.exception
    labels = [e.label for e in at.expander]
    assert any("2.0 Scope" in l for l in labels)
    assert any("4.0 Procedure" in l for l in labels)


def test_page_high_risk_group_defaults_expanded():
    at = _run_page_with(_ALL_CATEGORY_CHANGES)
    assert not at.exception
    header_expander = next(e for e in at.expander if "Headers" in e.label)
    # AppTest's Expander element exposes the expanded flag via .proto.expanded,
    # not a top-level .expanded attribute - verified empirically before writing
    # this plan (a top-level .expanded does not exist on this Streamlit version).
    assert header_expander.proto.expanded is True


def test_page_no_high_risk_group_defaults_collapsed():
    low_risk_change = {
        "change_id": "b2", "section": "6.0 Quality Control Release", "source": "Body",
        "change_type": "section_reordered", "old_text": "6.0", "new_text": "6.0",
        "ai_risk_level": "Informational", "reviewer_risk_level": None, "reason": "moved",
    }
    at = _run_page_with([low_risk_change])
    assert not at.exception
    body_section_expander = next(e for e in at.expander if "6.0 Quality Control Release" in e.label)
    assert body_section_expander.proto.expanded is False


def test_page_table_category_shows_table_id_row_col_columns():
    at = _run_page_with(_ALL_CATEGORY_CHANGES)
    assert not at.exception
    table_values = [t.value for t in at.table]
    matching = [df for df in table_values if "Table ID" in df.columns]
    assert len(matching) == 1
    df = matching[0]
    assert list(df.columns) == ["Table ID", "Row", "Col", "Old Text", "New Text", "Change Type", "Risk", "Reason"]
    assert df.iloc[0]["Row"] == "1"
    assert df.iloc[0]["Col"] == "2"


def test_page_body_category_has_no_table_cell_column():
    at = _run_page_with(_ALL_CATEGORY_CHANGES)
    assert not at.exception
    table_values = [t.value for t in at.table]
    body_style = [df for df in table_values if "Table ID" not in df.columns]
    assert len(body_style) >= 1
    for df in body_style:
        assert "Table Cell" not in df.columns
        assert "Source" not in df.columns


def test_page_filters_narrow_results_within_groups():
    at = _run_page_with(_ALL_CATEGORY_CHANGES)
    risk_selectbox = at.selectbox[0]  # "Filter by risk" is the first selectbox on the page
    risk_selectbox.select("High").run()
    assert not at.exception
    labels = [e.label for e in at.expander]
    # With only High-risk changes surviving the filter, Body's only change (Medium) is filtered
    # out, so Body should show 0 changes while Headers/Tables (both High) still show theirs.
    assert any(l == "Body — 0 changes" for l in labels)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && python -m pytest tests/test_page_detailed_changes.py -v`
Expected: the two pre-existing tests still PASS (page still works with the old implementation). All 8 new tests FAIL — the old page renders zero `st.expander`s (still a flat `st.table`), so tests using `next(... for ... in at.expander if ...)` fail with `StopIteration`, and the two `st.table`-column tests fail with `AssertionError` since the old table's column names don't match.

- [ ] **Step 3: Rewrite `2_Detailed_Changes.py`**

Replace the entire contents of `frontend/pages/2_Detailed_Changes.py` with:

```python
import streamlit as st

from logic import filter_changes, group_changes_for_display, format_group_label, has_high_risk, format_table_coordinates
from bootstrap import ensure_backend_running

st.set_page_config(layout="wide")

ensure_backend_running()

st.title("Detailed Changes")

comparison = st.session_state.get("comparison")

if not comparison:
    st.info("Upload and compare two documents on the 'Upload & Compare' page first.")
else:
    changes = comparison["changes"]
    sections = sorted({c["section"] for c in changes})
    change_types = sorted({c["change_type"] for c in changes})

    risk_filter = st.selectbox("Filter by risk", ["All", "High", "Medium", "Low", "Informational"])
    section_filter = st.selectbox("Filter by section", ["All"] + sections)
    type_filter = st.selectbox("Filter by change type", ["All"] + change_types)

    filtered = filter_changes(
        changes,
        risk=None if risk_filter == "All" else risk_filter,
        section=None if section_filter == "All" else section_filter,
        change_type=None if type_filter == "All" else type_filter,
    )

    grouped = group_changes_for_display(filtered)

    def render_body_rows(group_changes):
        st.table([
            {
                "Old Text": c["old_text"],
                "New Text": c["new_text"],
                "Change Type": c["change_type"],
                "Risk": c.get("reviewer_risk_level") or c["ai_risk_level"],
                "Reason": c["reason"],
            }
            for c in group_changes
        ])

    def render_table_rows(group_changes):
        rows = []
        for c in group_changes:
            table_id, row, col = format_table_coordinates(c.get("old_table_position"), c.get("new_table_position"))
            rows.append({
                "Table ID": table_id,
                "Row": row,
                "Col": col,
                "Old Text": c["old_text"],
                "New Text": c["new_text"],
                "Change Type": c["change_type"],
                "Risk": c.get("reviewer_risk_level") or c["ai_risk_level"],
                "Reason": c["reason"],
            })
        st.table(rows)

    for category in ("Headers", "Footers"):
        category_changes = grouped[category]
        with st.expander(format_group_label(category, category_changes), expanded=has_high_risk(category_changes)):
            if category_changes:
                render_body_rows(category_changes)
            else:
                st.caption("No changes.")

    for category, render_rows in (("Body", render_body_rows), ("Tables", render_table_rows)):
        sections_for_category = grouped[category]
        all_category_changes = [c for section_changes in sections_for_category.values() for c in section_changes]
        with st.expander(format_group_label(category, all_category_changes), expanded=has_high_risk(all_category_changes)):
            if not sections_for_category:
                st.caption("No changes.")
            for section_name, section_changes in sections_for_category.items():
                with st.expander(format_group_label(section_name, section_changes), expanded=has_high_risk(section_changes)):
                    render_rows(section_changes)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd frontend && python -m pytest tests/test_page_detailed_changes.py -v`
Expected: all tests pass, including the two pre-existing ones.

- [ ] **Step 5: Run the full frontend suite**

Run: `cd frontend && python -m pytest -q`
Expected: all tests pass, no regressions in `test_page_change_summary.py` or `test_page_review_and_export.py` (neither imports from `2_Detailed_Changes.py`, so they're unaffected).

- [ ] **Step 6: Manual verification in the browser**

Start the backend (`cd backend && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000`) and frontend (`cd frontend && python -m streamlit run Home.py`) per this project's normal local-dev commands. Upload `test-documents/docx/AllFeaturesDemo_v1.docx` and `AllFeaturesDemo_v2.docx` (already exist in this repo, cover Headers, Body, Text Box, Footnote, and Table changes in one comparison) on the Upload & Compare page, then open Detailed Changes. Confirm: all four categories appear in the fixed order; Headers/Tables/Body (which have High-risk changes in this document) start expanded, Footers (0 changes) starts collapsed; each Body/Tables section nests correctly under its category; the Tables category's rows show Table ID/Row/Col as real columns, not a squished string; the existing filters still narrow what's shown.

- [ ] **Step 7: Commit**

```bash
git add frontend/pages/2_Detailed_Changes.py frontend/tests/test_page_detailed_changes.py
git commit -m "feat: reorganize Detailed Changes page into Headers/Footers/Body/Tables groups"
```
