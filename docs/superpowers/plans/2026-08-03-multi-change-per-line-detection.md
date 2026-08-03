# Multi-Change-Per-Line Detection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A single changed paragraph can now produce more than one `Change` row when it genuinely contains more than one kind of edit (e.g. a unit change and a numeric change, or a numeric change and a separate wording change), instead of silently reporting only the first thing found.

**Architecture:** Two-phase detection per paragraph pair, replacing today's single-branch "regex or AI, whichever fires first" logic: (1) run all regex detectors (not just the first match) → one `Change` row per hit; (2) strip whatever text each detector matched and compare what's left — if anything still differs, send the *original full paragraph* to the AI for one more row, with a hint about what regex already found so it doesn't restate it. Works identically for TXT/DOCX/PDF since it operates purely on already-extracted `Paragraph.text`.

**Tech Stack:** Existing backend only — `app/regex_detectors.py`, `app/models.py`, `app/pipeline.py`, `app/llm_classifier.py`. No new dependencies.

## Global Constraints

- No format-specific work anywhere in this plan — this lives entirely below extraction, operating on `Paragraph.text` strings that are already format-agnostic by the time they reach these files.
- Two changes on one line are reported as **two separate `Change` rows** (same section, same repeated old/new text, independent `change_type`/`risk`/`reason` each) — never merged into one combined row.
- `detect_regex_change` (the existing first-match-wins function in `regex_detectors.py`) stays **unmodified** — it has its own dedicated test (`test_date_change_takes_priority_over_numeric` in `test_regex_detectors.py`) that must keep passing exactly as today. The new `detect_all_regex_changes` function is added *alongside* it, not as a replacement, and `pipeline.py` switches to calling the new one.
- When a residual triggers an AI call, the AI receives the **full original** old/new paragraph text, never the stripped/masked fragment. The prompt gains an optional per-item hint listing what regex already found, instructing the model to report only a genuinely distinct additional change.
- The `Change` dataclass in `models.py` gets **no new fields** for this feature — "what regex already found for this pending item" is tracked as a local mapping inside `pipeline.py`, not stored on `Change` itself, since `Change` is also used for storage/export and this data is only needed transiently while building the AI batch request.
- `risk_rules.py`, `paragraph_diff.py`, `move_reconciliation.py`, `export.py`, and the frontend need no changes — confirm this stays true; if any task discovers otherwise, stop and flag it rather than making an undocumented change.

---

### Task 1: Broaden regex detection to find all matches, and support residual-checking

**Files:**
- Modify: `backend/app/models.py` (the `RegexDetection` dataclass)
- Modify: `backend/app/regex_detectors.py`
- Test: `backend/tests/test_regex_detectors.py`

**Interfaces:**
- Consumes: nothing new — this task only touches already-existing code in these two files.
- Produces: `RegexDetection.old_values: list[str]` and `RegexDetection.new_values: list[str]` (new fields, in addition to the existing `change_type`, `reason`, `confidence`). `detect_all_regex_changes(old_text: str, new_text: str) -> list[RegexDetection]`. `strip_detected_values(old_text: str, new_text: str, detections: list[RegexDetection]) -> tuple[str, str]`. Task 2 imports and calls both of these new functions by these exact names.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_regex_detectors.py` (append at the end of the file; do not modify anything above):

```python
from app.regex_detectors import detect_all_regex_changes, strip_detected_values


def test_detect_all_regex_changes_finds_both_unit_and_numeric_on_one_line():
    detections = detect_all_regex_changes("Dispense 10 mL of solution.", "Dispense 20 L of solution.")
    change_types = {d.change_type for d in detections}
    assert change_types == {"unit_change", "numeric_change"}


def test_detect_all_regex_changes_returns_empty_list_when_nothing_matches():
    detections = detect_all_regex_changes(
        "The Quality Control Manager shall approve the result.",
        "The Quality Assurance Manager shall approve the result.",
    )
    assert detections == []


def test_regex_detection_carries_raw_matched_values():
    detections = detect_all_regex_changes(
        "Assay acceptance criterion: 95.0% to 105.0%.",
        "Assay acceptance criterion: 98.0% to 102.0%.",
    )
    assert len(detections) == 1
    assert detections[0].old_values == ["95.0", "105.0"]
    assert detections[0].new_values == ["98.0", "102.0"]


def test_strip_detected_values_leaves_no_residual_when_regex_explains_everything():
    old_text = "Dispense 10 mL of solution."
    new_text = "Dispense 20 L of solution."
    detections = detect_all_regex_changes(old_text, new_text)
    stripped_old, stripped_new = strip_detected_values(old_text, new_text, detections)
    assert stripped_old == stripped_new


def test_strip_detected_values_leaves_a_residual_when_something_else_also_changed():
    old_text = "Weigh 50 mg of sample, thoroughly mixed."
    new_text = "Weigh 55 mg of sample, completely mixed."
    detections = detect_all_regex_changes(old_text, new_text)
    stripped_old, stripped_new = strip_detected_values(old_text, new_text, detections)
    assert stripped_old != stripped_new


def test_detect_all_regex_changes_no_longer_hides_a_higher_risk_change_behind_a_lower_risk_one():
    # Regression guard for the first-match-wins severity-masking bug: date_change (Medium
    # risk) is checked before numeric_change (High risk) in detect_regex_change's fixed
    # order, so a line with both used to silently report only the Medium-risk one. Verified
    # directly while writing this plan: both genuinely fire on this exact pair.
    detections = detect_all_regex_changes(
        "Sample collected on 01 Jan 2024, weight 50 mg.",
        "Sample collected on 15 Mar 2024, weight 55 mg.",
    )
    change_types = {d.change_type for d in detections}
    assert change_types == {"date_change", "numeric_change"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `backend/`): `pytest tests/test_regex_detectors.py -v -k "all_regex_changes or strip_detected or carries_raw or hides_a_higher_risk"`
Expected: FAIL — `detect_all_regex_changes`, `strip_detected_values`, and `RegexDetection.old_values`/`new_values` don't exist yet.

- [ ] **Step 3: Add the new fields to `RegexDetection`**

In `backend/app/models.py`, find:

```python
@dataclass
class RegexDetection:
    change_type: str
    reason: str
    confidence: float = 1.0
```

Replace with:

```python
@dataclass
class RegexDetection:
    change_type: str
    reason: str
    confidence: float = 1.0
    old_values: list[str] = field(default_factory=list)
    new_values: list[str] = field(default_factory=list)
```

At the top of `models.py`, the import line currently reads `from dataclasses import dataclass`. Change it to:

```python
from dataclasses import dataclass, field
```

- [ ] **Step 4: Populate the new fields in each detector, and add the two new functions**

In `backend/app/regex_detectors.py`, replace the three detector functions and the final `detect_regex_change` function with:

```python
def detect_date_change(old_text: str, new_text: str) -> RegexDetection | None:
    old_dates = _extract_dates(old_text)
    new_dates = _extract_dates(new_text)
    if old_dates != new_dates:
        return RegexDetection(
            change_type="date_change",
            reason=f"Date changed from {', '.join(old_dates)} to {', '.join(new_dates)}.",
            old_values=old_dates,
            new_values=new_dates,
        )
    return None


def detect_unit_change(old_text: str, new_text: str) -> RegexDetection | None:
    old_units = _extract_units(old_text)
    new_units = _extract_units(new_text)
    if old_units != new_units:
        return RegexDetection(
            change_type="unit_change",
            reason=f"Unit changed from {old_units} to {new_units}.",
            old_values=old_units,
            new_values=new_units,
        )
    return None


def detect_numeric_change(old_text: str, new_text: str) -> RegexDetection | None:
    old_numbers = _extract_numbers(old_text)
    new_numbers = _extract_numbers(new_text)
    if old_numbers != new_numbers:
        return RegexDetection(
            change_type="numeric_change",
            reason=f"Numeric value(s) changed from {', '.join(old_numbers)} to {', '.join(new_numbers)}.",
            old_values=old_numbers,
            new_values=new_numbers,
        )
    return None


def detect_regex_change(old_text: str, new_text: str) -> RegexDetection | None:
    for detector in (detect_date_change, detect_unit_change, detect_numeric_change):
        result = detector(old_text, new_text)
        if result:
            return result
    return None


def detect_all_regex_changes(old_text: str, new_text: str) -> list[RegexDetection]:
    detections = []
    for detector in (detect_date_change, detect_unit_change, detect_numeric_change):
        result = detector(old_text, new_text)
        if result:
            detections.append(result)
    return detections


def strip_detected_values(old_text: str, new_text: str, detections: list["RegexDetection"]) -> tuple[str, str]:
    stripped_old = old_text
    stripped_new = new_text
    for detection in detections:
        for value in detection.old_values:
            stripped_old = stripped_old.replace(value, "", 1)
        for value in detection.new_values:
            stripped_new = stripped_new.replace(value, "", 1)
    return stripped_old, stripped_new
```

`detect_regex_change` is unchanged in behavior (still first-match-wins) — only re-pasted here because its neighbors changed; do not alter its body.

- [ ] **Step 5: Run the new tests, then the full regex_detectors suite**

Run: `pytest tests/test_regex_detectors.py -v`
Expected: PASS — all tests, including the 5 pre-existing ones (`test_numeric_change_when_only_numbers_differ`, `test_unit_change_when_unit_token_differs`, `test_date_change_takes_priority_over_numeric`, `test_no_detection_when_text_has_no_numbers_units_or_dates`, `test_numeric_change_does_not_absorb_trailing_sentence_period`, `test_extract_numbers_excludes_a_bare_trailing_period`) plus the 6 new ones, all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/models.py backend/app/regex_detectors.py backend/tests/test_regex_detectors.py
git commit -m "feat: broaden regex detection to find all matches and support residual-checking"
```

---

### Task 2: Wire multi-row detection into the pipeline

**Files:**
- Modify: `backend/app/pipeline.py`
- Test: `backend/tests/test_pipeline.py`

**Interfaces:**
- Consumes: `regex_detectors.detect_all_regex_changes(old_text, new_text) -> list[RegexDetection]` and `regex_detectors.strip_detected_values(old_text, new_text, detections) -> tuple[str, str]` from Task 1, imported exactly as those names.
- Produces: `_build_paragraph_changes(section_heading: str, old_p: Paragraph, new_p: Paragraph) -> tuple[list[Change], dict[str, list[str]]]` — replaces `_build_paragraph_change` (singular) entirely. The second element of the tuple maps `change_id` → the list of `change_type` strings regex already found for that same paragraph pair, for any pending (AI-bound) `Change` the function returns; Task 3 consumes this mapping by this exact shape.

**Context: why an existing test's expected numbers change in this task.** `test_pipeline_reproduces_the_outline_example`'s second fixture line — `"Samples shall be stored at 25°C ± 2°C."` → `"Samples shall be stored at 25°C ± 2°C and 60% RH ± 5% RH."` — already contains a genuine compound change (a unit change AND a numeric change AND an added humidity-control clause), which is exactly the kind of case this whole plan exists to fix. Today's first-match-wins code only ever reports `unit_change` for that line; this task correctly makes it report `unit_change`, `numeric_change`, and one AI-classified row for the added clause — three rows instead of one. This was verified directly (not assumed) while writing this plan:

```python
# verified interactively: after Task 1's strip_detected_values on this exact pair,
# stripped_old = 'Samples shall be stored at  °C .'          (digits/unit symbols removed)
# stripped_new = 'Samples shall be stored at  °C  and  RH  RH.'
# stripped_old != stripped_new -> a residual genuinely exists (the word "RH" and the
# added clause structure are not digit/unit tokens, so stripping doesn't remove them)
```

Do not treat the resulting test-number changes below as a mistake to "fix back" — they are the intended, verified consequence of the fix.

- [ ] **Step 1: Update `test_pipeline_reproduces_the_outline_example` and add two new tests**

In `backend/tests/test_pipeline.py`, replace the entire `test_pipeline_reproduces_the_outline_example` function with:

```python
def test_pipeline_reproduces_the_outline_example(monkeypatch):
    old_paragraphs = [
        Paragraph(text="Assay acceptance criterion: 95.0% to 105.0%."),
        Paragraph(text="Samples shall be stored at 25°C ± 2°C."),
        Paragraph(text="The Quality Control Manager shall approve the result."),
    ]
    new_paragraphs = [
        Paragraph(text="Assay acceptance criterion: 98.0% to 102.0%."),
        Paragraph(text="Samples shall be stored at 25°C ± 2°C and 60% RH ± 5% RH."),
        Paragraph(text="The Quality Assurance Manager shall approve the result."),
    ]

    def fake_classify(unresolved):
        results = []
        for item in unresolved:
            if "Manager" in item["old_text"]:
                results.append(LLMClassification(
                    change_id=item["change_id"],
                    change_type="role_responsibility_change",
                    reason="Approval responsibility changed from QC Manager to QA Manager.",
                    confidence=0.9,
                ))
            else:
                results.append(LLMClassification(
                    change_id=item["change_id"],
                    change_type="qualitative_specification_change",
                    reason="An additional environmental control requirement (humidity) was added.",
                    confidence=0.85,
                ))
        return results

    monkeypatch.setattr(llm_classifier, "classify_changes_batch", fake_classify)

    result = pipeline.compare_documents(old_paragraphs, new_paragraphs, "SOP_v1.txt", "SOP_v2.txt")

    # 5 rows total: line 1 -> numeric_change (1); line 2 -> unit_change + numeric_change
    # + one AI-classified row for the added humidity clause (3); line 3 -> one AI-classified
    # role_responsibility_change row (1).
    assert result.summary.total_changes == 5
    assert result.summary.high_risk == 4
    assert result.summary.medium_risk == 1

    change_types = {c.change_type for c in result.changes}
    assert "numeric_change" in change_types
    assert "unit_change" in change_types
    assert "role_responsibility_change" in change_types

    # This is the row this whole feature exists to add: line 2 alone must now produce
    # 3 distinct rows instead of 1.
    samples_changes = [c for c in result.changes if c.old_text == "Samples shall be stored at 25°C ± 2°C."]
    assert len(samples_changes) == 3
    assert {c.change_type for c in samples_changes} == {
        "unit_change", "numeric_change", "qualitative_specification_change",
    }

    role_change = next(c for c in result.changes if c.change_type == "role_responsibility_change")
    assert role_change.ai_risk_level == "Medium"
    assert "QA Manager" in role_change.reason
```

Then add two new tests to the same file:

```python
def test_two_regex_detections_on_one_line_produce_two_rows_and_skip_ai(monkeypatch):
    old_paragraphs = [Paragraph(text="Dispense 10 mL of solution.")]
    new_paragraphs = [Paragraph(text="Dispense 20 L of solution.")]

    def fail_if_called(unresolved):
        raise AssertionError("classify_changes_batch should not be called - regex fully explains this line")

    monkeypatch.setattr(llm_classifier, "classify_changes_batch", fail_if_called)

    result = pipeline.compare_documents(old_paragraphs, new_paragraphs, "old.txt", "new.txt")

    assert result.summary.total_changes == 2
    assert {c.change_type for c in result.changes} == {"unit_change", "numeric_change"}


def test_regex_detection_plus_separate_wording_change_produces_two_rows(monkeypatch):
    old_paragraphs = [Paragraph(text="Weigh 50 mg of sample, thoroughly mixed.")]
    new_paragraphs = [Paragraph(text="Weigh 55 mg of sample, completely mixed.")]

    def fake_classify(unresolved):
        assert len(unresolved) == 1
        assert unresolved[0]["already_detected"] == ["numeric_change"]
        return [LLMClassification(
            change_id=unresolved[0]["change_id"],
            change_type="qualitative_specification_change",
            reason="The mixing descriptor was changed from thoroughly to completely.",
            confidence=0.9,
        )]

    monkeypatch.setattr(llm_classifier, "classify_changes_batch", fake_classify)

    result = pipeline.compare_documents(old_paragraphs, new_paragraphs, "old.txt", "new.txt")

    assert result.summary.total_changes == 2
    change_types = {c.change_type for c in result.changes}
    assert change_types == {"numeric_change", "qualitative_specification_change"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_pipeline.py -v`
Expected: FAIL — `_build_paragraph_changes` doesn't exist yet, `compare_documents` still only produces one row per line, and the "already_detected" key doesn't exist in the batch call.

- [ ] **Step 3: Rewrite `_build_paragraph_change` as `_build_paragraph_changes`, and wire it into `compare_documents`**

In `backend/app/pipeline.py`, replace the `_build_paragraph_change` function with:

```python
def _build_paragraph_changes(
    section_heading: str, old_p: Paragraph, new_p: Paragraph
) -> tuple[list[Change], dict[str, list[str]]]:
    detections = regex_detectors.detect_all_regex_changes(old_p.text, new_p.text)
    changes: list[Change] = []
    for detection in detections:
        changes.append(Change(
            change_id=str(uuid.uuid4()), section=section_heading, change_type=detection.change_type,
            old_text=old_p.text, new_text=new_p.text, old_page=old_p.page, new_page=new_p.page,
            confidence=detection.confidence, ai_risk_level=risk_rules.assign_risk(detection.change_type),
            reason=detection.reason,
        ))

    already_detected_by_id: dict[str, list[str]] = {}
    stripped_old, stripped_new = regex_detectors.strip_detected_values(old_p.text, new_p.text, detections)
    if stripped_old != stripped_new:
        pending_id = str(uuid.uuid4())
        changes.append(Change(
            change_id=pending_id, section=section_heading, change_type="pending_llm_classification",
            old_text=old_p.text, new_text=new_p.text, old_page=old_p.page, new_page=new_p.page,
            confidence=0.0, ai_risk_level="Medium", reason="",
        ))
        already_detected_by_id[pending_id] = [d.change_type for d in detections]

    return changes, already_detected_by_id
```

Then update `compare_documents`. Find this block:

```python
            if op.tag == "replace":
                paired = min(len(op.old_paragraphs), len(op.new_paragraphs))
                for i in range(paired):
                    changes.append(_build_paragraph_change(old_sec.heading, op.old_paragraphs[i], op.new_paragraphs[i]))
                orphan_deletes += [(p, old_sec.heading) for p in op.old_paragraphs[paired:]]
                orphan_inserts += [(p, new_sec.heading) for p in op.new_paragraphs[paired:]]
```

Replace with:

```python
            if op.tag == "replace":
                paired = min(len(op.old_paragraphs), len(op.new_paragraphs))
                for i in range(paired):
                    para_changes, para_already_detected = _build_paragraph_changes(
                        old_sec.heading, op.old_paragraphs[i], op.new_paragraphs[i]
                    )
                    changes.extend(para_changes)
                    already_detected_by_id.update(para_already_detected)
                orphan_deletes += [(p, old_sec.heading) for p in op.old_paragraphs[paired:]]
                orphan_inserts += [(p, new_sec.heading) for p in op.new_paragraphs[paired:]]
```

This references `already_detected_by_id`, which needs to exist before the loop. Find:

```python
    changes: list[Change] = []
    orphan_deletes: list[Orphan] = []
    orphan_inserts: list[Orphan] = []
```

Replace with:

```python
    changes: list[Change] = []
    orphan_deletes: list[Orphan] = []
    orphan_inserts: list[Orphan] = []
    already_detected_by_id: dict[str, list[str]] = {}
```

Finally, find the batch-classification call:

```python
    pending = [c for c in changes if c.change_type == "pending_llm_classification"]
    if pending:
        classifications = llm_classifier.classify_changes_batch([
            {"change_id": c.change_id, "old_text": c.old_text, "new_text": c.new_text} for c in pending
        ])
```

Replace with:

```python
    pending = [c for c in changes if c.change_type == "pending_llm_classification"]
    if pending:
        classifications = llm_classifier.classify_changes_batch([
            {
                "change_id": c.change_id, "old_text": c.old_text, "new_text": c.new_text,
                "already_detected": already_detected_by_id.get(c.change_id, []),
            }
            for c in pending
        ])
```

The rest of `compare_documents` (moved/deleted/added paragraph handling, the classification-application loop, the final `ComparisonResult` construction) is unchanged.

- [ ] **Step 4: Run the pipeline tests, then the full backend suite**

Run: `pytest tests/test_pipeline.py -v`
Expected: PASS — both pre-existing tests (`test_pipeline_reproduces_the_outline_example` with its new numbers, `test_pending_change_never_leaks_when_llm_response_omits_it`) plus the 2 new ones.

Run (from `backend/`): `pytest -v`
Expected: PASS — full suite, no regressions anywhere else. `test_pending_change_never_leaks_when_llm_response_omits_it` uses a single-paragraph fixture with no regex match at all (`"The Quality Control Manager..."`), so it's unaffected by this task's changes — confirm it still passes unmodified.

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipeline.py backend/tests/test_pipeline.py
git commit -m "feat: allow one paragraph to produce multiple Change rows when it has multiple distinct edits"
```

---

### Task 3: Prompt the AI with what regex already found, to prevent duplicate reporting

**Files:**
- Modify: `backend/app/llm_classifier.py`
- Test: `backend/tests/test_llm_classifier.py`

**Interfaces:**
- Consumes: the `"already_detected": list[str]` key that Task 2 now includes in every dict passed to `classify_changes_batch` (present and possibly empty for every item, per Task 2's `already_detected_by_id.get(c.change_id, [])` default).
- Produces: no new function names — `_build_prompt`'s existing signature (`list[dict] -> str`) is unchanged; only its internal prompt text changes when an item's `already_detected` list is non-empty.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_llm_classifier.py`:

```python
def test_prompt_includes_already_detected_hint_when_present():
    unresolved = [
        {"change_id": "c1", "old_text": "a", "new_text": "b", "already_detected": ["numeric_change"]},
    ]
    prompt = llm_classifier._build_prompt(unresolved)
    assert "already_detected" in prompt
    assert "numeric_change" in prompt


def test_prompt_omits_already_detected_key_when_empty_or_absent():
    unresolved_empty = [{"change_id": "c1", "old_text": "a", "new_text": "b", "already_detected": []}]
    unresolved_absent = [{"change_id": "c1", "old_text": "a", "new_text": "b"}]
    prompt_empty = llm_classifier._build_prompt(unresolved_empty)
    prompt_absent = llm_classifier._build_prompt(unresolved_absent)
    assert '"already_detected"' not in prompt_empty
    assert '"already_detected"' not in prompt_absent
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_llm_classifier.py -v -k already_detected`
Expected: FAIL — `_build_prompt` doesn't emit `already_detected` anywhere yet.

- [ ] **Step 3: Update `_build_prompt`**

In `backend/app/llm_classifier.py`, replace `_build_prompt` with:

```python
def _build_prompt(unresolved: list[dict]) -> str:
    lines = [
        "You are reviewing paired old/new text from a revised pharmaceutical document.",
        "For each item, classify the change into exactly one of these types:",
        *[f"- {t}" for t in SEMANTIC_CHANGE_TYPES],
        "Respond ONLY with a JSON array. Each element must have keys:",
        '"change_id", "change_type", "reason" (one sentence), "confidence" (0.0-1.0).',
        "Some items include an \"already_detected\" list -- these are change types a separate",
        "automated check already found for that item. If present, classify only a genuinely",
        "distinct additional change beyond what's already listed; do not restate or",
        "re-describe the already-detected fact.",
        "",
        "Items:",
    ]
    for item in unresolved:
        entry = {
            "change_id": item["change_id"],
            "old_text": item["old_text"],
            "new_text": item["new_text"],
        }
        if item.get("already_detected"):
            entry["already_detected"] = item["already_detected"]
        lines.append(json.dumps(entry))
    return "\n".join(lines)
```

- [ ] **Step 4: Run the llm_classifier tests, then the full backend suite**

Run: `pytest tests/test_llm_classifier.py -v`
Expected: PASS — all pre-existing tests (`test_empty_input_returns_empty_list_without_calling_gemini`, `test_parses_successful_gemini_response`, `test_gemini_failure_falls_back_to_unclassified`) plus the 2 new ones.

Run (from `backend/`): `pytest -v`
Expected: PASS — full suite, no regressions.

- [ ] **Step 5: Commit**

```bash
git add backend/app/llm_classifier.py backend/tests/test_llm_classifier.py
git commit -m "feat: hint the AI classifier about changes regex already detected on the same line"
```
