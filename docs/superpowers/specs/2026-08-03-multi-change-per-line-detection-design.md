# Multi-Change-Per-Line Detection — Design

**Status:** Approved for implementation

## Purpose

The change-detection pipeline currently reports at most **one** `Change` per
paragraph pair, even when a single line genuinely contains two distinct
kinds of edits. Two separate gaps cause this:

1. `regex_detectors.detect_regex_change` checks date → unit → numeric and
   returns on the *first* match, never checking the remaining detectors. A
   line with both a unit change and a numeric change only ever reports the
   unit change.
2. Any regex match short-circuits the AI classification step entirely
   (`pipeline._build_paragraph_change` returns immediately on a regex hit).
   A line with a numeric change *and* a separate wording/semantic change
   never gets the wording half checked at all — the AI is never even
   asked.

This is not specific to any file format. By the time the pipeline reaches
classification, `regex_detectors` and the LLM classifier both operate
purely on `Paragraph.text` strings — the same code path runs regardless of
whether the paragraph was extracted from a `.txt`, `.docx`, or `.pdf` file.
Fixing this once in `pipeline.py`/`regex_detectors.py` fixes it for all
three formats simultaneously.

**Bonus fix included:** today's first-match-wins ordering (date checked
before unit checked before numeric) also means change *severity* can be
silently masked — a line with both a Medium-risk date change and a
High-risk numeric change currently reports only the date change, under-
representing the line's real risk. Reporting every detected change as its
own row with its own independently-assigned risk (via the existing
`risk_rules.assign_risk`) eliminates this masking as a side effect.

## Decision

Replace the single-branch "regex or AI" logic with a two-phase check per
paragraph pair, producing zero or more `Change` rows instead of exactly
one:

1. **Regex phase (broadened):** run all three regex detectors (date, unit,
   numeric) unconditionally instead of stopping at the first match. Each
   one that fires produces its own `Change` row — same classification,
   reason, and risk-assignment behavior as today, just no longer mutually
   exclusive with the others.
2. **Residual check:** take the raw old/new substrings each firing
   detector actually matched (not the formatted reason string — the real
   number/unit/date values) and strip them out of the paragraph's old and
   new text. Compare what's left:
   - Nothing left, or the stripped text is identical → the regex row(s)
     are the complete picture. No AI call for this paragraph.
   - The stripped text still differs → a residual change exists beyond
     what regex explained. Queue the paragraph for AI classification
     (same batched mechanism as today), producing one *additional* row.
3. **No regex match at all** (today's existing fallback): unchanged — the
   whole paragraph goes to the AI as a single candidate row.

A paragraph pair can now yield 0, 1, or more `Change` rows. A pure numeric
change still costs zero AI involvement — identical to today's behavior. A
numeric change plus a wording change now yields two rows: one from regex,
one from AI, with the AI asked about only the part regex couldn't explain.

**Reporting shape:** two separate rows, not one combined row. Each keeps
its own `Change.section`, repeats the same `old_text`/`new_text`, and
carries its own independent `change_type`, `risk`, and `reason`. This
preserves the existing "Filter by change type" exact-match behavior in the
frontend untouched, and lets two changes of different severity on the same
line show their true, independent risk levels rather than being forced
into one combined level.

## Design per component

### `backend/app/regex_detectors.py`

New function `detect_all_regex_changes(old_text: str, new_text: str) ->
list[RegexDetection]` replaces the role of `detect_regex_change` in the
pipeline (the single-match function can stay for any other caller, or be
retired if `pipeline.py` was its only caller — confirm during
implementation). It runs `detect_date_change`, `detect_unit_change`, and
`detect_numeric_change` unconditionally, collecting every one that returns
a hit, instead of returning after the first non-`None` result.

Each detector already extracts the specific old/new values that changed
(`old_dates`/`new_dates`, `old_units`/`new_units`, `old_numbers`/
`new_numbers`) to build its reason string — these raw lists need to be
attached to the returned `RegexDetection` (not just folded into the
formatted reason text) so the residual-stripping step can consume them
without re-parsing the reason string.

### `backend/app/models.py`

`RegexDetection` gains fields for the raw matched values, e.g.
`old_values: list[str]` and `new_values: list[str]`, alongside the
existing `change_type`, `reason`, `confidence`.

### `backend/app/pipeline.py`

`_build_paragraph_change` (singular, returns one `Change`) becomes
`_build_paragraph_changes` (plural, returns `list[Change]`):

1. Call `detect_all_regex_changes(old_p.text, new_p.text)`.
2. For each `RegexDetection` returned, build a `Change` row exactly as
   today (`change_type`, `reason`, `risk_rules.assign_risk(...)`).
3. Strip every detection's `old_values`/`new_values` out of `old_p.text`/
   `new_p.text` respectively, producing masked old/new strings.
4. If the masked strings still differ (or no regex detection fired at
   all), append one more placeholder row with
   `change_type="pending_llm_classification"` — identical in shape to
   today's no-match fallback, so the existing batch-classification step at
   the end of `compare_documents` needs no changes: it already just
   collects every row with that placeholder type and doesn't care how it
   got there.
5. Return the full list (0 or more rows).

The call site in `compare_documents` changes from
`changes.append(_build_paragraph_change(...))` to
`changes.extend(_build_paragraph_changes(...))`. No other change to
`compare_documents`'s structure.

### `backend/app/llm_classifier.py`

When a residual triggers an AI call, send the **full original** old/new
text to the LLM — not the stripped/masked fragment. A masked fragment
(e.g. "Weigh mg of sample, thoroughly mixed" after stripping "50") is
harder for the model to classify sensibly than the full sentence. To avoid
the AI re-reporting the same fact the regex already caught as a duplicate
row, extend `_build_prompt` to mention, for items where a regex detection
already fired, what was already found (e.g. "a numeric_change was already
detected in this pair separately") and instruct the model to report only a
genuinely distinct additional change if one exists, not restate the
already-caught fact.

### Unaffected

`risk_rules.py`, `paragraph_diff.py`, `move_reconciliation.py`,
`export.py`, and the frontend need no changes. `paragraph_diff.py`'s
"replace" opcode pairing is unaffected — this design only changes what
happens *after* a pair is identified, not the pairing logic itself.
Downstream consumers already treat `changes` as a flat `list[Change]`
regardless of how many rows came from one original paragraph pair versus
different ones, so one paragraph now producing 2 rows instead of 1 is
invisible past `pipeline.py`.

## Testing

- A line with two independently regex-detectable changes (e.g. unit *and*
  numeric both change) → assert exactly 2 `Change` rows, correct
  independent `change_type`/`risk` on each.
- A line with one regex-detectable change *and* a separate wording change
  → assert a regex row plus one AI-classified row (AI call mocked for a
  deterministic test), and that the AI row's `change_type` is not a
  duplicate of the regex row's.
- A line with a regex match where the stripped text is fully identical
  (no residual) → assert exactly 1 row, and that no AI call was made for
  this paragraph (mock should show zero invocations for it).
- A line with no regex match at all → unchanged existing behavior, 1
  AI-classified row.
- Full regression run of the existing test suite — every existing
  single-change-per-line test must continue passing unmodified, since
  this design is additive (more rows in compound cases) rather than a
  change to existing single-change classification.
- Known implementation-time edge case to test explicitly: overlapping
  regex matches, e.g. a unit-pattern match consuming a number
  (`"50 mg"` overlaps with `UNIT_PATTERN`'s `\d+\.?\d*\s*mg` and
  `NUMBER_PATTERN`'s standalone `50`) — stripping both detections' values
  must not corrupt the residual comparison (e.g. double-stripping the same
  substring, or stripping order producing a false residual).

## Out of Scope

- Format-specific work — this fix lives entirely below the extraction
  layer and applies identically to TXT, DOCX, and PDF without any
  per-format changes.
- Combining more than two change "kinds" into more than 2 rows per line is
  naturally supported by this design (the loop already handles 0+ regex
  detections, and a residual could theoretically still contain more than
  one AI-classifiable idea) but this spec does not add logic to split a
  *single* AI classification into multiple rows — the AI still returns one
  classification per residual, as today.
- Retroactively re-classifying already-completed comparisons — this only
  changes behavior for comparisons run after the fix lands.
