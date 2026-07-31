# Edge Case Test Documents — Design

**Status:** Approved for creation

## Purpose

Produce a small set of `.txt` document pairs (old/new) that exercise tricky,
non-obvious classification scenarios in the comparison pipeline, beyond the
baseline SOP pair already created. Scope is **classification coverage only**
— these are not robustness/crash tests (empty files, bad encoding, etc.).

Organized as three thematic pairs rather than many isolated pairs, so there
are only a handful of files to upload and click through, at the cost of
needing the expected-results table to pin down which change caused which
reported result.

## Deliverables

Three `.txt` pairs saved to `test-documents/`, each with an accompanying
expected-results table (same format as the original SOP pair): section,
change, expected `change_type`, expected risk, and notes — including cases
where the "expected" result is genuinely uncertain/ambiguous by design, not
a strict pass/fail.

## Pair A — Deterministic Detector Edge Cases

Targets `regex_detectors.py`'s numeric/unit/date detection specifically.

- ISO-format date change (`2024-01-15` → `2024-03-20`) — the date regex only
  matches `"01 Jan 2024"`-style text, not ISO format, so this is expected to
  fall through to the numeric detector and register as `numeric_change`
  instead of `date_change` — a real, known gap worth confirming.
- Negative number change (`-20°C` → `-70°C`)
- Comma-thousands-separator number change (`1,000 mg` → `2,000 mg`) — the
  number regex doesn't handle commas, so the extracted numbers will likely
  be garbled (e.g. `"1"`/`"000"` as separate tokens); still expected to
  register *some* numeric_change, just with a messy reason string.
- A sentence with two numbers changing at once, only one of which matters
- A unit-only change with the number unchanged (`10 mL` → `10 L`)
- A control sentence with numbers present but unchanged — confirms no false
  positive

## Pair B — Semantic/LLM Edge Cases

Targets `llm_classifier.py`'s judgment calls on non-numeric rewording.

- Capitalization-only change — tests whether this reads as `formatting_only`
  or something else
- True synonym substitution, no meaning change — targets
  `clarification_no_meaning_change`
- Clean positive cases: a real role/responsibility change, a real
  reference-document change, a real process-sequence change
- A deliberately ambiguous case readable as either a process-sequence change
  or a mere clarification — there's no "correct" answer here, the point is
  observing how the LLM resolves genuine ambiguity

## Pair C — Structural / Document-Shape Edge Cases

Targets `sectioning.py`, `section_matching.py`, and `move_reconciliation.py`.

- No numbered headings at all (plain prose) — forces the one-section-per-
  paragraph fallback
- Two sections reordered/moved wholesale between versions (content
  unchanged, only position changes)
- A duplicate heading appearing twice in the same document
- A section added (no counterpart in the old version)
- A section deleted (no counterpart in the new version)
- A section's heading reworded, body unchanged (e.g. "5.2 Sample
  Preparation" → "5.2 Preparing the Sample")
- A section renumbered only — heading wording and body both otherwise
  identical (e.g. "5.2 Sample Preparation" → "6.1 Sample Preparation").
  **Expected: zero reported changes for this section** — the pipeline only
  diffs paragraphs within a matched section, never the heading text itself,
  so a pure renumbering is currently invisible to the report. This is a
  real limitation being documented via test, not fixed.
- A paragraph that moves to a new section *and* is slightly reworded at the
  same time — tests the edge of move-reconciliation's 0.85 similarity
  threshold; may legitimately show up as a separate delete+add instead of a
  `moved_paragraph`, which is a valid (if imprecise) outcome, not a failure
- A decimal-number table-like line (e.g. `10.5 | 20.3 | conforms`) — tests
  whether the heading-detection regex false-positives on it
- One section left completely identical — control case

## Out of Scope

- Robustness/crash testing (empty files, encoding issues, malformed
  structure, huge documents)
- PDF/DOCX-specific edge cases (heading-style detection, embedded TOC
  matching) — this set is TXT only
