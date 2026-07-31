# Section-Matching Threshold & Number Regex Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix two issues found during edge-case testing: a false section match caused by an over-permissive section-matching threshold, and a number-extraction regex that absorbs a trailing sentence period into the number.

**Architecture:** Two independent one-line fixes in the existing backend — no new files, no interface changes. Task 1 fixes the regex; Task 2 raises the threshold. Order doesn't matter functionally, but Task 1 is done first since it's the more contained, lower-risk change.

**Tech Stack:** Python, existing `backend/app/regex_detectors.py` and `backend/app/section_matching.py`.

## Global Constraints

- `NUMBER_PATTERN`'s fix must not change behavior for numbers that already parse correctly today (e.g. `"95.0"`, `"-20"`, `"1,000"` parsing as `"1"`/`"000"`) — only the trailing-bare-period case changes.
- `match_sections`'s threshold change is the default parameter value only — the function signature (`embed_fn`, `threshold` as a keyword-overridable parameter) does not change, so no caller needs updating.
- Every existing test in `backend/tests/` must still pass after both changes — this is not a new feature, it's fixing observed incorrect behavior in already-shipped code.

---

### Task 1: Fix `NUMBER_PATTERN`'s trailing-period bug

**Files:**
- Modify: `backend/app/regex_detectors.py:5`
- Test: `backend/tests/test_regex_detectors.py`

**Interfaces:**
- Consumes: nothing new
- Produces: no interface change — `detect_numeric_change`, `detect_regex_change` keep their existing signatures; only the extracted number strings change for the specific trailing-period case

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_regex_detectors.py`:

```python
def test_numeric_change_does_not_absorb_trailing_sentence_period():
    result = detect_regex_change(
        "This procedure is effective from 2024-01-15.",
        "This procedure is effective from 2024-03-20.",
    )
    assert result is not None
    assert result.change_type == "numeric_change"
    assert "-15." not in result.reason
    assert "-20." not in result.reason
    assert "-15" in result.reason
    assert "-20" in result.reason
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `backend/`): `pytest tests/test_regex_detectors.py::test_numeric_change_does_not_absorb_trailing_sentence_period -v`
Expected: FAIL — the reason string contains `"-15."` and `"-20."` (with the trailing periods), so the `not in` assertions fail.

- [ ] **Step 3: Fix `NUMBER_PATTERN`**

In `backend/app/regex_detectors.py`, change line 5 from:

```python
NUMBER_PATTERN = re.compile(r"-?\d+\.?\d*")
```

to:

```python
NUMBER_PATTERN = re.compile(r"-?\d+(?:\.\d+)?")
```

The non-capturing group `(?:\.\d+)?` requires at least one digit after a decimal point for the group to match at all — a bare trailing period with nothing after it is no longer consumed as part of the number. This has zero capturing groups (same as before), so `NUMBER_PATTERN.findall(text)` continues to return full match strings, not group contents.

- [ ] **Step 4: Run the new test and the full regex detector suite to verify they pass**

Run: `pytest tests/test_regex_detectors.py -v`
Expected: PASS (5 tests — the 4 existing ones plus the new one)

- [ ] **Step 5: Run the full backend suite to confirm no regression**

Run: `pytest -v`
Expected: PASS (all tests, no change in count from before this task other than the one new test)

- [ ] **Step 6: Commit**

```bash
git add backend/app/regex_detectors.py backend/tests/test_regex_detectors.py
git commit -m "fix: NUMBER_PATTERN no longer absorbs a bare trailing sentence period"
```

---

### Task 2: Raise the section-matching threshold from 0.5 to 0.6

**Files:**
- Modify: `backend/app/section_matching.py:19`
- Test: `backend/tests/test_section_matching.py`

**Interfaces:**
- Consumes: nothing new
- Produces: no interface change — `match_sections`'s signature is unchanged; only its default `threshold` value changes. Existing tests that pass `threshold=0.5` explicitly are unaffected by this change since they don't rely on the default.

- [ ] **Step 1: Write the failing test**

This test reproduces the exact real-world false match found during testing
(`C1_v1.txt`/`C1_v2.txt`'s "Batch Record Archival" vs "Long-Term Sample
Retention", which scored 0.588) using a fake embedding function with a
hand-crafted score matrix, so it runs fast and deterministically without
needing the real model. Add to `backend/tests/test_section_matching.py`:

```python
def test_default_threshold_excludes_a_058_similarity_match():
    old_sections = [
        Section(heading="Deleted Section", paragraphs=[Paragraph(text="unrelated old content")]),
    ]
    new_sections = [
        Section(heading="Added Section", paragraphs=[Paragraph(text="unrelated new content")]),
    ]

    def fake_058_embed_fn(texts: list[str]) -> np.ndarray:
        # Two vectors with cosine similarity of exactly 0.588 - mirrors the
        # real false-match score found when testing C1_v1.txt/C1_v2.txt.
        # Keyed by exact _section_text output (heading + " " + body),
        # since match_sections calls embed_fn separately for old and new
        # texts and each call must return one row per input string.
        vector_by_text = {
            "Deleted Section unrelated old content": np.array([1.0, 0.0]),
            "Added Section unrelated new content": np.array([0.588, (1 - 0.588 ** 2) ** 0.5]),
        }
        return np.array([vector_by_text[t] for t in texts])

    result = match_sections(old_sections, new_sections, embed_fn=fake_058_embed_fn)

    assert result.matches == []
    assert result.deleted_indices == [0]
    assert result.inserted_indices == [0]
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `backend/`): `pytest tests/test_section_matching.py::test_default_threshold_excludes_a_058_similarity_match -v`
Expected: FAIL — at the current default threshold of 0.5, a 0.588 similarity score is above threshold, so the sections incorrectly match instead of showing as deleted/inserted.

- [ ] **Step 3: Raise the threshold**

In `backend/app/section_matching.py`, change line 19 from:

```python
    threshold: float = 0.5,
```

to:

```python
    threshold: float = 0.6,
```

- [ ] **Step 4: Run the new test and the full section matching suite to verify they pass**

Run: `pytest tests/test_section_matching.py -v`
Expected: PASS (3 tests — the 2 existing ones plus the new one)

- [ ] **Step 5: Run the full backend suite to confirm no regression**

Run: `pytest -v`
Expected: PASS (all tests). Pay particular attention to `test_pipeline.py`,
which calls `match_sections` with the default threshold against real
embeddings (not a fake function) — this is the one test in the suite that
would actually catch a real-world regression from this threshold change.

- [ ] **Step 6: Manually re-verify the original false-match scenario is fixed**

Run (from `backend/`):

```bash
python -c "
from app.extraction import extract_text
from app.sectioning import split_into_sections
from app.section_matching import match_sections

base = 'c:/life/internship/aizent/doc version project/test-documents/'
old_paragraphs = extract_text(base + 'C1_v1.txt', 'txt')
new_paragraphs = extract_text(base + 'C1_v2.txt', 'txt')
old_sections = split_into_sections(old_paragraphs)
new_sections = split_into_sections(new_paragraphs)
result = match_sections(old_sections, new_sections)
print('4.0 Batch Record Archival matched:', any(old_sections[m.old_index].heading == '4.0 Batch Record Archival' for m in result.matches))
"
```

Expected: prints `4.0 Batch Record Archival matched: False`, and the console debug output (from the existing `print()` statements in `match_sections`) shows `4.0 Batch Record Archival` under `DELETED`, not `MATCHED`.

- [ ] **Step 7: Commit**

```bash
git add backend/app/section_matching.py backend/tests/test_section_matching.py
git commit -m "fix: raise section-matching threshold to 0.6 to exclude coincidental vocabulary-only matches"
```
