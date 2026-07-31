# Section-Matching Threshold & Number Regex Fixes — Design

**Status:** Approved for implementation

## Purpose

Fix two issues found while testing the edge-case document set
(`test-documents/A*.txt`, `B*.txt`, `C1*.txt`, `C2*.txt`):

1. A false section match in `C1_v1.txt`/`C1_v2.txt`: an unrelated deleted
   section ("4.0 Batch Record Archival") got matched against an unrelated
   added section ("10.0 Long-Term Sample Retention") purely because they
   share the phrase "batch record," producing a misleading
   `reference_document_change` instead of a clean delete + add.
2. A cosmetic regex quirk in numeric-change detection: a sentence-ending
   period with no digits after it gets absorbed into the extracted number
   (e.g. `"-15."` instead of `"-15"`), making reason text look garbled.

## Fix 1: Raise the section-matching threshold

**Root cause (confirmed empirically, not guessed):** running
`section_matching.match_sections` directly against the C1 pair showed the
false match scored 0.588 — genuinely above the current 0.5 threshold, not a
borderline case right at the boundary. The greedy matcher's highest-score-
first processing let a correct, high-scoring self-match (0.911) consume its
row before a higher-scoring but still-plausible pairing (0.596) could be
considered, leaving the false match (0.588) as the only remaining candidate
above threshold for the leftover column.

Every correctly-matched section pair in this test scored 0.911 or higher.
Raising the threshold from **0.5 to 0.6** excludes the 0.588 false match
while keeping meaningful margin below every observed correct match.

**Known limitation of this fix:** there is no test case in the current
document set exercising a section matched purely on meaning with
substantially different wording in both heading and body (the scenario the
design was originally built to handle, e.g. "5.2 Sample Preparation" →
"6.1 Preparation of Sample Solution"). It's possible such a match could
score lower than the ones observed here. 0.6 is chosen deliberately as a
modest raise (not e.g. 0.8+) to leave margin for that case, but this is a
residual risk to watch for in future testing, not something this fix
resolves definitively.

**Change:** `backend/app/section_matching.py` — `match_sections`'s default
`threshold` parameter: `0.5` → `0.6`.

## Fix 2: Correct the number regex's decimal-point handling

**Root cause:** `regex_detectors.py`'s `NUMBER_PATTERN = re.compile(r"-?\d+\.?\d*")`
allows an optional `.` followed by zero-or-more digits. Since both the dot
and the digit count are independently optional, a lone trailing period with
no digits after it (e.g. the period ending a sentence right after a number)
gets matched as part of the number.

**Change:** `backend/app/regex_detectors.py` — `NUMBER_PATTERN`:
`r"-?\d+\.?\d*"` → `r"-?\d+(?:\.\d+)?"`. The non-capturing group requires at
least one digit after a decimal point for the group to match at all, so a
bare trailing period is no longer consumed.

## Testing

- `section_matching.py`'s existing unit tests (Task 5) use injected fake
  embedding functions with hand-crafted scores — the threshold constant
  doesn't affect their correctness, only the real-model integration test in
  `test_pipeline.py` (Task 12) and the C1 scenario above exercise real
  scores. Add one test to `test_regex_detectors.py` covering a number
  immediately followed by a sentence-ending period with no trailing digit,
  asserting the extracted number excludes the period.
- Re-run the full backend suite after both changes to confirm no
  regression (particularly `test_pipeline.py`, which uses real embeddings).
- Manually re-run the C1 pair through `section_matching.match_sections`
  (as done during investigation) to confirm the false match no longer
  occurs at threshold 0.6.

## Out of Scope

- Problem #3 from testing (LLM risk calibration on near-synonym wording
  changes) — deferred, needs more test cases before it's clear whether it's
  a pattern worth addressing or a one-off.
- A more robust fix for the underlying greedy-matching limitation (e.g.
  weighting heading similarity separately from body similarity, or
  requiring a confidence margin between best and second-best candidates) —
  not pursued now since the threshold raise resolves the observed case with
  the evidence available; worth revisiting if a similar false match shows
  up with genuinely different documents.
