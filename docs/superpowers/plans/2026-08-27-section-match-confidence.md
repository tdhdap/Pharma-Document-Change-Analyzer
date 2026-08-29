# Section Match Confidence and Traceability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show the real match score on every section row produced by matching, and state explicitly when a heading was matched on body content despite differing substantially.

**Architecture:** `SectionMatch.score` is already computed and currently discarded into a debug `print`. Three `Change` constructions stop hardcoding `confidence=1.0` and take it. `detect_section_heading_changed` additionally compares the two headings *with their numbers stripped* and appends a clause to its reason when they differ substantially. The frontend gains a `Match` column populated only for match-derived change types.

**Tech Stack:** Python 3.14, sentence-transformers, Streamlit, pytest.

## Global Constraints

- **`backend/app/section_structure.py` — the main file this plan edits — contains TWO sets of unrelated uncommitted changes** (the user's cascading-renumbering fix and an earlier task's pattern widening) that the user intends to commit themselves. Stage files by name. **Never `git add -A`, never `git commit -a`.** If you cannot stage a file, **STOP and report** — do not reconstruct the file from HEAD, which would destroy that work.
- Never read or write `backend/app.db` — it is the user's real database.
- **No schema change and no migration.** `confidence` already exists in `models.py`, `db.py`, and both exports.
- Do not change how sections are matched, or the `0.6` matching threshold.
- `detect_section_added` and `detect_section_deleted` must **not** change. They never receive `matches` and have no score.
- Backend is green at 340 tests and frontend at 78 before this work starts.

## Prior verification

The whole design was prototyped against the live code and reverted before this plan was written. The code below is the code that ran. Findings:

- Only **two** existing tests break: `test_pure_rewording_is_detected` (backend, needs the clause appended to its expected reason — the heading pair scores 0.24) and `test_page_table_category_shows_row_col_columns_1_indexed` (frontend, needs `"Match"` in its expected column list).
- On the real corpus the clause fires on exactly three rows — `2.0 Scope`→`2.0 Applicability` twice (0.29) and `5.0 Equipment Qualification`→`5.0 Qualifying the Equipment` (0.76) — and on **no** renumber.
- **The existing number-stripping skip block must not be reused for the clause.** It only skips when *both* headings carry a number. Folding the helper into it would make `2.0 Scope` → `Scope` (number removed) compare equal and be silently suppressed — a false negative that does not exist today.
- `app.embeddings` imports only numpy and sentence-transformers, so importing it into `section_structure` creates no cycle.

## File Structure

- `backend/app/section_structure.py` — one import, one constant, two helpers, three `confidence` sites, one reason block.
- `backend/tests/test_section_structure.py` — one updated test, new tests.
- `frontend/logic.py` — one change-type set, one formatter.
- `frontend/pages/2_Detailed_Changes.py` — one import, one dict key in each of three renderers.
- `frontend/tests/test_logic.py`, `frontend/tests/test_page_detailed_changes.py` — new tests, one updated.

---

### Task 1: Carry the real match score onto section rows

**Files:**
- Modify: `backend/app/section_structure.py`
- Test: `backend/tests/test_section_structure.py`

**Interfaces:**
- Consumes: `SectionMatch.score`, already in scope in all three loops.
- Produces: `section_renumbered`, `section_renumbered_cascade`, `section_reordered`, and `section_heading_changed` rows whose `confidence` is the match score.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_section_structure.py`:

```python
def test_matched_section_rows_carry_the_real_match_score():
    old_sections = [Section(heading="2.0 Acceptance Criteria", paragraphs=[Paragraph(text="body")])]
    new_sections = [Section(heading="3.0 Acceptance Criteria", paragraphs=[Paragraph(text="body")])]
    matches = [SectionMatch(old_index=0, new_index=0, score=0.87)]

    changes = detect_section_renumbering(matches, old_sections, new_sections)

    assert changes[0].confidence == 0.87


def test_added_and_deleted_sections_keep_confidence_of_one():
    # These sections were never matched - there is no score to report, and
    # inventing one would be the same lie as the hardcoded 1.0 being removed
    # elsewhere. Their blank Match column is produced by the frontend instead.
    added = detect_section_added([0], [Section(heading="9.0 New", paragraphs=[Paragraph(text="body")])])
    deleted = detect_section_deleted([0], [Section(heading="9.0 Old", paragraphs=[Paragraph(text="body")])])

    assert added[0].confidence == 1.0
    assert deleted[0].confidence == 1.0
```

- [ ] **Step 2: Run the tests to verify the first fails**

Run: `cd backend && python -m pytest tests/test_section_structure.py -k "real_match_score or keep_confidence_of_one" -v`
Expected: `test_matched_section_rows_carry_the_real_match_score` FAILS (`1.0 != 0.87`); the second already passes and is a guard.

- [ ] **Step 3: Replace the hardcoded confidence in the three matched detectors**

In `detect_section_renumbering` and `detect_section_reordering`, change:

```python
            confidence=m.score, ai_risk_level=risk_rules.assign_risk(change_type),
```

Both sites currently read `confidence=1.0` and are followed by `reason=reason, source="Body",`. Make the same change in `detect_section_heading_changed`.

**Do not touch `detect_section_added` or `detect_section_deleted`.** They receive `inserted_indices` / `deleted_indices`, never `matches`, and have no `m` in scope.

- [ ] **Step 4: Run the tests**

Run: `cd backend && python -m pytest tests/test_section_structure.py -q`
Expected: PASS.

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && python -m pytest -q`
Expected: 342 pass. No existing test asserts a section row's confidence.

- [ ] **Step 6: Commit**

```bash
git add backend/app/section_structure.py backend/tests/test_section_structure.py
git commit -m "feat: report the real section match score instead of a hardcoded confidence"
```

Verify with `git diff --cached backend/app/section_structure.py` that the staged diff contains **only** your three `confidence` lines. That file also holds two sets of the user's uncommitted work. If staging fails, STOP and report.

---

### Task 2: State when a heading was matched on content

**Files:**
- Modify: `backend/app/section_structure.py`
- Test: `backend/tests/test_section_structure.py`

**Interfaces:**
- Produces: `HEADING_REWRITE_SIMILARITY_THRESHOLD`, `_heading_text_without_number(heading) -> str`, `_heading_rewrite_similarity(old_heading, new_heading) -> float`.

- [ ] **Step 1: Write the failing tests**

```python
def test_heading_rewrite_similarity_ignores_the_number():
    # With the number left in, a pure renumber scores 0.782 while a genuine
    # rewrite scores 0.869 - the number inverts the signal. Stripped, a renumber
    # is exactly 1.0.
    assert _heading_rewrite_similarity("4.0 Approval", "2.0 Approval") == 1.0


def test_heading_rewrite_similarity_falls_for_a_real_rewrite():
    assert _heading_rewrite_similarity("2.0 Scope", "2.0 Applicability") < 0.85


def test_heading_rewrite_similarity_stays_high_for_a_trivial_edit():
    assert _heading_rewrite_similarity("4.0 Approval", "4.0 Approvals") >= 0.85


def test_substantially_changed_heading_says_it_matched_on_content():
    old_sections = [Section(heading="2.0 Scope", paragraphs=[Paragraph(text="Applies to all batches.")])]
    new_sections = [Section(heading="2.0 Applicability", paragraphs=[Paragraph(text="Applies to all batches.")])]
    matches = [SectionMatch(old_index=0, new_index=0, score=0.89)]

    changes = detect_section_heading_changed(matches, old_sections, new_sections)

    assert "sections matched on content" in changes[0].reason
    assert "Headings differ substantially" in changes[0].reason


def test_a_trivially_changed_heading_does_not_claim_a_judgment_call():
    old_sections = [Section(heading="4.0 Approval", paragraphs=[Paragraph(text="QA approves.")])]
    new_sections = [Section(heading="4.0 Approvals", paragraphs=[Paragraph(text="QA approves.")])]
    matches = [SectionMatch(old_index=0, new_index=0, score=0.98)]

    changes = detect_section_heading_changed(matches, old_sections, new_sections)

    assert "matched on content" not in changes[0].reason


def test_removing_a_heading_number_is_still_reported():
    # Guard: the clause must not be wired into the existing number-stripping skip.
    # That skip only fires when BOTH headings are numbered; reusing it here would
    # make this pair compare equal and vanish.
    old_sections = [Section(heading="2.0 Scope", paragraphs=[Paragraph(text="body")])]
    new_sections = [Section(heading="Scope", paragraphs=[Paragraph(text="body")])]
    matches = [SectionMatch(old_index=0, new_index=0, score=0.95)]

    changes = detect_section_heading_changed(matches, old_sections, new_sections)

    assert len(changes) == 1
    assert "matched on content" not in changes[0].reason
```

Import the two helpers and `detect_section_heading_changed` in the file's existing `from app.section_structure import (...)` block.

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && python -m pytest tests/test_section_structure.py -k "heading_rewrite or matched_on_content or judgment_call or removing_a_heading_number" -v`
Expected: FAIL — the helpers do not exist.

- [ ] **Step 3: Add the import and threshold**

At the top of `backend/app/section_structure.py`:

```python
from app import risk_rules
from app.embeddings import cosine_similarity_matrix, embed_texts
from app.models import Change, Paragraph, Section, SectionMatch

# Below this, two headings are different enough that pairing their sections was a
# judgment call made on body content, and the reviewer is told so. Chosen from
# measured separation: real rewrites scored 0.106-0.759, trivial edits
# (pluralisation, "and"->"&", "Scope"->"Scope and Purpose") scored 0.831-0.976.
HEADING_REWRITE_SIMILARITY_THRESHOLD = 0.85
```

- [ ] **Step 4: Add the two helpers**

Immediately above `_is_top_level_numbered`:

```python
def _heading_text_without_number(heading: str) -> str:
    split = _split_heading_number(heading)
    return split[1] if split is not None else " ".join(heading.split())


def _heading_rewrite_similarity(old_heading: str, new_heading: str) -> float:
    # Compare the headings WITHOUT their numbers. With the number left in, a pure
    # renumber ('4.0 Approval' -> '2.0 Approval') scores 0.782 while a genuine
    # rewrite ('Equipment Qualification' -> 'Qualifying the Equipment') scores
    # 0.869 - the number inverts the signal. Stripped, renumbers land at exactly
    # 1.000 and the rewrites fall to 0.288 and 0.759.
    old_rest = _heading_text_without_number(old_heading)
    new_rest = _heading_text_without_number(new_heading)
    if old_rest == new_rest:
        return 1.0
    return float(cosine_similarity_matrix(
        embed_texts([old_rest]), embed_texts([new_rest])
    )[0][0])
```

- [ ] **Step 5: Append the clause**

In `detect_section_heading_changed`, replace the final block. Before:

```python
        change_type = "section_heading_changed"
        changes.append(Change(
            change_id=str(uuid.uuid4()), section=old_heading, change_type=change_type,
            old_text=old_heading, new_text=new_heading, old_page=None, new_page=None,
            confidence=m.score, ai_risk_level=risk_rules.assign_risk(change_type),
            reason=f"Section heading changed from '{old_heading}' to '{new_heading}'.",
            source="Body",
        ))
```

After:

```python
        change_type = "section_heading_changed"
        reason = f"Section heading changed from '{old_heading}' to '{new_heading}'."
        # Only say this where the pairing was genuinely a judgment call. The whole
        # point is that the overall match score cannot reveal it: a rewrite scored
        # 0.976 and a pure renumber 0.979 on the real corpus.
        similarity = _heading_rewrite_similarity(old_heading, new_heading)
        if similarity < HEADING_REWRITE_SIMILARITY_THRESHOLD:
            reason += (
                f" Headings differ substantially (similarity {similarity:.2f}); "
                "sections matched on content."
            )
        changes.append(Change(
            change_id=str(uuid.uuid4()), section=old_heading, change_type=change_type,
            old_text=old_heading, new_text=new_heading, old_page=None, new_page=None,
            confidence=m.score, ai_risk_level=risk_rules.assign_risk(change_type),
            reason=reason,
            source="Body",
        ))
```

**Leave the existing number-stripping skip block above completely untouched.**

- [ ] **Step 6: Update the one existing test that breaks**

`test_pure_rewording_is_detected` asserts an exact reason. Its pair
(`8.0 Deviation Handling` → `8.0 Non-Conformance Management`) scores **0.24**, so
the clause now appends. Change its assertion to:

```python
    assert c.reason == (
        "Section heading changed from '8.0 Deviation Handling' to "
        "'8.0 Non-Conformance Management'. Headings differ substantially "
        "(similarity 0.24); sections matched on content."
    )
```

- [ ] **Step 7: Run the full backend suite**

Run: `cd backend && python -m pytest -q`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add backend/app/section_structure.py backend/tests/test_section_structure.py
git commit -m "feat: state when a section heading was matched on content"
```

Same staging discipline as Task 1.

---

### Task 3: Show the Match column

**Files:**
- Modify: `frontend/logic.py`, `frontend/pages/2_Detailed_Changes.py`
- Test: `frontend/tests/test_logic.py`, `frontend/tests/test_page_detailed_changes.py`

**Interfaces:**
- Produces: `format_match_confidence(change: dict) -> str` — the score to two decimals for match-derived types, `""` otherwise.

- [ ] **Step 1: Write the failing tests**

In `frontend/tests/test_logic.py`:

```python
def test_format_match_confidence_shows_the_score_for_matched_rows():
    for change_type in (
        "section_heading_changed", "section_renumbered", "section_renumbered_cascade",
        "section_reordered", "moved_paragraph", "moved_table_content",
    ):
        assert format_match_confidence({"change_type": change_type, "confidence": 0.893}) == "0.89"


def test_format_match_confidence_is_blank_where_nothing_was_matched():
    # An added or deleted section was never matched, so there is no score. A regex
    # or LLM row's confidence is a different metric entirely and must not appear
    # in a column labelled Match.
    for change_type in ("section_added", "section_deleted", "numeric_change", "table_row_added"):
        assert format_match_confidence({"change_type": change_type, "confidence": 1.0}) == ""


def test_format_match_confidence_survives_a_missing_confidence():
    assert format_match_confidence({"change_type": "section_reordered"}) == ""
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd frontend && python -m pytest tests/test_logic.py -k match_confidence -v`
Expected: FAIL — `format_match_confidence` does not exist.

- [ ] **Step 3: Add the set and formatter**

In `frontend/logic.py`, immediately after `_WHOLE_SECTION_CHANGE_TYPES`:

```python
# Only these rows are produced by matching one thing to another, so only these
# have a match score worth showing. section_added/section_deleted are absent on
# purpose: those sections were never matched, so there is no score, and the blank
# tells the reviewer that. Regex- and LLM-derived rows are absent because their
# confidence means something else entirely (a regex is deterministic, an LLM is
# grading itself) and mixing metrics in one column invites misreading.
_MATCH_DERIVED_CHANGE_TYPES = {
    "section_heading_changed",
    "section_renumbered",
    "section_renumbered_cascade",
    "section_reordered",
    "moved_paragraph",
    "moved_table_content",
}


def format_match_confidence(change: dict) -> str:
    if change.get("change_type") not in _MATCH_DERIVED_CHANGE_TYPES:
        return ""
    confidence = change.get("confidence")
    if confidence is None:
        return ""
    return f"{confidence:.2f}"
```

- [ ] **Step 4: Add the column to all three renderers**

In `frontend/pages/2_Detailed_Changes.py`, extend the import:

```python
    format_table_coordinates, table_group_key, format_match_confidence,
```

Then in `render_header_footer_rows`, `render_body_rows`, and `render_table_rows`, add this key immediately after the `"Change Type"` key and before `"Risk"` (matching each renderer's own indentation):

```python
                "Match": format_match_confidence(c),
```

- [ ] **Step 5: Update the one existing test that breaks**

`test_page_table_category_shows_row_col_columns_1_indexed` asserts an exact column list. Update it to:

```python
    assert list(df.columns) == ["Row", "Col", "Old Text", "New Text", "Change Type", "Match", "Risk", "Reason"]
```

- [ ] **Step 6: Add a rendering test**

Append to `frontend/tests/test_page_detailed_changes.py`. It uses the
`_run_page_with` helper already defined in that file:

```python
def test_page_shows_match_score_only_for_matched_rows():
    changes = [
        {
            "change_id": "m1", "section": "2.0 Scope", "source": "Body",
            "change_type": "section_heading_changed",
            "old_text": "2.0 Scope", "new_text": "2.0 Applicability",
            "confidence": 0.893, "ai_risk_level": "Medium", "reviewer_risk_level": None,
            "reason": "Section heading changed.",
        },
        {
            "change_id": "m2", "section": "9.0 Training", "source": "Body",
            "change_type": "section_added",
            "old_text": "", "new_text": "9.0 Training",
            "confidence": 1.0, "ai_risk_level": "High", "reviewer_risk_level": None,
            "reason": "Section added.",
        },
    ]

    at = _run_page_with(changes)

    assert not at.exception
    rendered = [df.value for df in at.get("table")]
    match_values = [v for df in rendered for v in df["Match"].tolist()]
    assert "0.89" in match_values
    assert "" in match_values
```

If the page renders each section under its own table, both rows still appear
across the collected tables, which is why the assertion pools every rendered
table's `Match` column rather than assuming a single one.

- [ ] **Step 7: Run both suites**

Run: `cd frontend && python -m pytest -q` and `cd backend && python -m pytest -q`
Expected: all pass.

- [ ] **Step 8: Corpus check**

Run every DOCX pair in `test-documents/docx/` through `pipeline.compare_documents` with `llm_classifier.classify_changes_batch` stubbed. Confirm the clause appears on exactly three rows (`2.0 Scope`→`2.0 Applicability` twice at 0.29, `5.0 Equipment Qualification`→`5.0 Qualifying the Equipment` at 0.76), on no renumber, and that the set of rows produced is otherwise unchanged.

- [ ] **Step 9: Commit**

```bash
git add frontend/logic.py frontend/pages/2_Detailed_Changes.py frontend/tests/test_logic.py frontend/tests/test_page_detailed_changes.py
git commit -m "feat: show a Match column for rows produced by matching"
```
