# Movement Must Not Hide Content Changes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop a paragraph's relocation from hiding an edit to its text — when content both moves and changes, report the move and the content change as separate findings.

**Architecture:** `pipeline.py` currently has two disjoint paths for changed content: paragraphs edited in place go through `_build_paragraph_changes` (regex detectors + AI classification), while moved paragraphs go through their own loop that emits one move row and runs no detection at all. The fix reuses the existing `_build_paragraph_changes` inside the moved loop, giving moved content identical scrutiny to stationary content. Because that function already returns nothing when the two texts match, pure relocations produce no extra rows.

**Tech Stack:** Python, FastAPI backend, pytest.

## Global Constraints

- The content-change rows for a moved paragraph carry `mv.new_section` as their `section` — not the old section, and not the compound `"old -> new"` label. (spec: "Attribution")
- The move row itself is unchanged: it keeps its compound `"{old_section} -> {new_section}"` section label, its own `change_type`, and its own risk. (spec: "Risk levels stay separate and unmodified")
- The dict returned by `_build_paragraph_changes` must be merged into the pipeline's existing `already_detected_by_id`, so the AI classifier is told which change types the regexes already caught. (spec: "The returned `already_detected_by_id` must be merged")
- A pure move (identical old/new text) must produce **exactly one** change — the move row — and no content-change rows. (spec: "A pure move produces zero extra rows")
- Do not modify `move_reconciliation.py`, the 0.85 similarity threshold, or the `RISK_TABLE` entries for `moved_paragraph`/`moved_table_content`. All explicitly out of scope. (spec: "Out of Scope")
- The new code must sit before the `pending_llm_classification` resolution block at the end of `compare_documents`, so queued placeholders get resolved. The moved loop already sits above that block. (spec: "Design per component")

---

### Task 1: Run content detection on moved paragraphs

**Files:**
- Modify: `backend/app/pipeline.py` (inside `compare_documents`, the `for mv in moved:` loop)
- Test: `backend/tests/test_pipeline.py`

**Interfaces:**
- Consumes: `_build_paragraph_changes(section_heading: str, old_p: Paragraph, new_p: Paragraph) -> tuple[list[Change], dict[str, list[str]]]` — already defined at the top of `backend/app/pipeline.py`. Unchanged by this task.
- Consumes: `mv` items from `move_reconciliation.reconcile_moves`, each a `MovedParagraph` with `.old_paragraph`, `.new_paragraph`, `.old_section`, `.new_section`, `.score`.
- Produces: no new functions or types. This task only adds `Change` rows to the existing output list.

`backend/tests/test_pipeline.py` already imports everything these tests need — `from app import pipeline, llm_classifier` and `from app.models import Paragraph, LLMClassification, TableCoordinate`. Do not add imports.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_pipeline.py`:

```python
def test_moved_paragraph_that_was_also_edited_reports_both_move_and_content_change(monkeypatch):
    # A relocation must never mask an edit: a spec value changing while the
    # paragraph moves is exactly the high-consequence case the 0.85 move-matching
    # threshold is most likely to swallow.
    def fail_if_called(unresolved):
        raise AssertionError("no AI call expected - the numeric regex fully explains this change")

    monkeypatch.setattr(llm_classifier, "classify_changes_batch", fail_if_called)

    old_paragraphs = [
        Paragraph(text="1.0 Purpose"),
        Paragraph(text="This SOP defines tablet compression for all product lines."),
        Paragraph(text="Compression force shall be maintained at 15 kN."),
        Paragraph(text="2.0 Storage"),
        Paragraph(text="Store finished product in a controlled warehouse area."),
    ]
    new_paragraphs = [
        Paragraph(text="1.0 Purpose"),
        Paragraph(text="This SOP defines tablet compression for all product lines."),
        Paragraph(text="2.0 Storage"),
        Paragraph(text="Store finished product in a controlled warehouse area."),
        Paragraph(text="Compression force shall be maintained at 18 kN."),
    ]

    result = pipeline.compare_documents(old_paragraphs, new_paragraphs, "old.txt", "new.txt")

    change_types = [c.change_type for c in result.changes]
    assert "moved_paragraph" in change_types
    assert "numeric_change" in change_types


def test_moved_paragraph_content_change_is_filed_under_the_new_section(monkeypatch):
    def fail_if_called(unresolved):
        raise AssertionError("no AI call expected")

    monkeypatch.setattr(llm_classifier, "classify_changes_batch", fail_if_called)

    old_paragraphs = [
        Paragraph(text="1.0 Purpose"),
        Paragraph(text="This SOP defines tablet compression for all product lines."),
        Paragraph(text="Compression force shall be maintained at 15 kN."),
        Paragraph(text="2.0 Storage"),
        Paragraph(text="Store finished product in a controlled warehouse area."),
    ]
    new_paragraphs = [
        Paragraph(text="1.0 Purpose"),
        Paragraph(text="This SOP defines tablet compression for all product lines."),
        Paragraph(text="2.0 Storage"),
        Paragraph(text="Store finished product in a controlled warehouse area."),
        Paragraph(text="Compression force shall be maintained at 18 kN."),
    ]

    result = pipeline.compare_documents(old_paragraphs, new_paragraphs, "old.txt", "new.txt")

    numeric = [c for c in result.changes if c.change_type == "numeric_change"]
    assert len(numeric) == 1
    # Filed where the paragraph now lives, so it groups with that section's other
    # changes in the UI - not under the move row's compound "old -> new" label.
    assert numeric[0].section == "2.0 Storage"


def test_moved_paragraph_content_change_carries_its_own_real_risk(monkeypatch):
    def fail_if_called(unresolved):
        raise AssertionError("no AI call expected")

    monkeypatch.setattr(llm_classifier, "classify_changes_batch", fail_if_called)

    old_paragraphs = [
        Paragraph(text="1.0 Purpose"),
        Paragraph(text="This SOP defines tablet compression for all product lines."),
        Paragraph(text="Compression force shall be maintained at 15 kN."),
        Paragraph(text="2.0 Storage"),
        Paragraph(text="Store finished product in a controlled warehouse area."),
    ]
    new_paragraphs = [
        Paragraph(text="1.0 Purpose"),
        Paragraph(text="This SOP defines tablet compression for all product lines."),
        Paragraph(text="2.0 Storage"),
        Paragraph(text="Store finished product in a controlled warehouse area."),
        Paragraph(text="Compression force shall be maintained at 18 kN."),
    ]

    result = pipeline.compare_documents(old_paragraphs, new_paragraphs, "old.txt", "new.txt")

    numeric = [c for c in result.changes if c.change_type == "numeric_change"]
    # The whole point of the fix: severity rides on its own row instead of being
    # downgraded to the move row's default.
    assert numeric[0].ai_risk_level == "High"


def test_moved_table_content_that_was_also_edited_reports_both(monkeypatch):
    def fail_if_called(unresolved):
        raise AssertionError("no AI call expected")

    monkeypatch.setattr(llm_classifier, "classify_changes_batch", fail_if_called)

    position = TableCoordinate(table_id=0, row=1, col=2)
    old_paragraphs = [
        Paragraph(text="1.0 Purpose"),
        Paragraph(text="This SOP defines the tablet compression process fully."),
        Paragraph(text="Assay limit 95.0 percent", from_table=True, table_position=position),
        Paragraph(text="2.0 Storage"),
        Paragraph(text="Store finished product in a controlled warehouse area."),
    ]
    new_paragraphs = [
        Paragraph(text="1.0 Purpose"),
        Paragraph(text="This SOP defines the tablet compression process fully."),
        Paragraph(text="2.0 Storage"),
        Paragraph(text="Store finished product in a controlled warehouse area."),
        Paragraph(text="Assay limit 98.0 percent", from_table=True, table_position=position),
    ]

    result = pipeline.compare_documents(old_paragraphs, new_paragraphs, "old.txt", "new.txt")

    change_types = [c.change_type for c in result.changes]
    assert "moved_table_content" in change_types
    numeric = [c for c in result.changes if c.change_type == "numeric_change"]
    assert len(numeric) == 1
    assert numeric[0].source == "Table"
    assert numeric[0].new_table_position == position


def test_pure_move_with_identical_text_produces_only_the_move_row(monkeypatch):
    # Regression guard: the fix must not duplicate-report relocations that
    # didn't change anything.
    def fail_if_called(unresolved):
        raise AssertionError("no AI call expected for an unchanged relocation")

    monkeypatch.setattr(llm_classifier, "classify_changes_batch", fail_if_called)

    old_paragraphs = [
        Paragraph(text="1.0 Purpose"),
        Paragraph(text="This SOP defines tablet compression for all product lines."),
        Paragraph(text="Compression force shall be maintained at 15 kN."),
        Paragraph(text="2.0 Storage"),
        Paragraph(text="Store finished product in a controlled warehouse area."),
    ]
    new_paragraphs = [
        Paragraph(text="1.0 Purpose"),
        Paragraph(text="This SOP defines tablet compression for all product lines."),
        Paragraph(text="2.0 Storage"),
        Paragraph(text="Store finished product in a controlled warehouse area."),
        Paragraph(text="Compression force shall be maintained at 15 kN."),
    ]

    result = pipeline.compare_documents(old_paragraphs, new_paragraphs, "old.txt", "new.txt")

    assert len(result.changes) == 1
    assert result.changes[0].change_type == "moved_paragraph"


def test_moved_paragraph_with_semantic_only_change_is_ai_classified(monkeypatch):
    def fake_classify(unresolved):
        return [
            LLMClassification(
                change_id=item["change_id"],
                change_type="role_responsibility_change",
                reason="Approval responsibility changed.",
                confidence=0.9,
            )
            for item in unresolved
        ]

    monkeypatch.setattr(llm_classifier, "classify_changes_batch", fake_classify)

    old_paragraphs = [
        Paragraph(text="1.0 Purpose"),
        Paragraph(text="This SOP defines tablet compression for all product lines."),
        Paragraph(text="The QC Manager shall approve the completed batch record."),
        Paragraph(text="2.0 Storage"),
        Paragraph(text="Store finished product in a controlled warehouse area."),
    ]
    new_paragraphs = [
        Paragraph(text="1.0 Purpose"),
        Paragraph(text="This SOP defines tablet compression for all product lines."),
        Paragraph(text="2.0 Storage"),
        Paragraph(text="Store finished product in a controlled warehouse area."),
        Paragraph(text="The QA Manager shall approve the completed batch record."),
    ]

    result = pipeline.compare_documents(old_paragraphs, new_paragraphs, "old.txt", "new.txt")

    change_types = [c.change_type for c in result.changes]
    assert "moved_paragraph" in change_types
    assert "role_responsibility_change" in change_types
    # The internal placeholder must never survive into the report.
    assert "pending_llm_classification" not in change_types


def test_moved_paragraph_tells_the_ai_which_change_types_regex_already_caught(monkeypatch):
    # A moved paragraph carrying BOTH a numeric edit and a residual semantic edit
    # must pass the already_detected hint through, so the AI classifies only the
    # genuinely distinct change instead of restating the numeric one.
    captured = {}

    def capturing_classify(unresolved):
        captured["items"] = unresolved
        return [
            LLMClassification(
                change_id=item["change_id"],
                change_type="role_responsibility_change",
                reason="Approval responsibility changed.",
                confidence=0.9,
            )
            for item in unresolved
        ]

    monkeypatch.setattr(llm_classifier, "classify_changes_batch", capturing_classify)

    old_paragraphs = [
        Paragraph(text="1.0 Purpose"),
        Paragraph(text="This SOP defines tablet compression for all product lines."),
        Paragraph(text="The QC Manager shall verify 15 kN compression force."),
        Paragraph(text="2.0 Storage"),
        Paragraph(text="Store finished product in a controlled warehouse area."),
    ]
    new_paragraphs = [
        Paragraph(text="1.0 Purpose"),
        Paragraph(text="This SOP defines tablet compression for all product lines."),
        Paragraph(text="2.0 Storage"),
        Paragraph(text="Store finished product in a controlled warehouse area."),
        Paragraph(text="The QA Manager shall verify 18 kN compression force."),
    ]

    result = pipeline.compare_documents(old_paragraphs, new_paragraphs, "old.txt", "new.txt")

    assert captured["items"], "the AI classifier should have been called"
    assert captured["items"][0]["already_detected"] == ["numeric_change"]
    change_types = [c.change_type for c in result.changes]
    assert "numeric_change" in change_types
    assert "role_responsibility_change" in change_types
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_pipeline.py -k moved -v`

Expected: the pure-move test (`test_pure_move_with_identical_text_produces_only_the_move_row`) PASSES already — the current code emits exactly the one move row, which is the behavior this test is guarding, not changing. Every other new test FAILS, because the current code emits only the move row and never runs content detection:
- `..._reports_both_move_and_content_change` → `AssertionError` on `"numeric_change" in change_types`
- `..._filed_under_the_new_section` → `AssertionError` on `len(numeric) == 1` (list is empty)
- `..._carries_its_own_real_risk` → `IndexError` on `numeric[0]` (list is empty)
- `..._moved_table_content_that_was_also_edited_reports_both` → `AssertionError` on `len(numeric) == 1`
- `..._semantic_only_change_is_ai_classified` → `AssertionError` on `"role_responsibility_change" in change_types`
- `..._tells_the_ai_which_change_types_regex_already_caught` → `AssertionError` on `captured["items"]` (the classifier is never called)

- [ ] **Step 3: Apply the fix**

In `backend/app/pipeline.py`, find the end of the `for mv in moved:` loop — the `changes.append(Change(...))` that emits the move row, immediately followed by the `for p, section in remaining_deletes:` loop:

```python
            reason=reason, source=source,
            old_table_position=mv.old_paragraph.table_position, new_table_position=mv.new_paragraph.table_position,
        ))

    for p, section in remaining_deletes:
```

Replace with:

```python
            reason=reason, source=source,
            old_table_position=mv.old_paragraph.table_position, new_table_position=mv.new_paragraph.table_position,
        ))
        # A relocation must not hide an edit. Reusing the same detection path a
        # stationary edited paragraph gets means moved content is scrutinised
        # identically - regex detectors plus AI classification for whatever they
        # don't explain. When the text is unchanged this returns nothing, so pure
        # moves stay a single row. Filed under new_section because that is where
        # the paragraph now lives, and where a reviewer will look for it.
        moved_content_changes, moved_already_detected = _build_paragraph_changes(
            mv.new_section, mv.old_paragraph, mv.new_paragraph
        )
        changes.extend(moved_content_changes)
        already_detected_by_id.update(moved_already_detected)

    for p, section in remaining_deletes:
```

Note the indentation: the new lines sit **inside** the `for mv in moved:` loop (8 spaces), aligned with the `changes.append(...)` above them.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_pipeline.py -k moved -v`
Expected: all 7 new tests pass, plus the pre-existing `test_pipeline_content_moved_into_a_new_section_is_reported_as_moved_not_deleted` (which is a pure move, so it must be unaffected).

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && python -m pytest -q`
Expected: all tests pass — 265 (258 existing + 7 new), no failures, no regressions.

- [ ] **Step 6: Commit**

```bash
git add backend/app/pipeline.py backend/tests/test_pipeline.py
git commit -m "fix: run content detection on moved paragraphs so moves cannot hide edits"
```
