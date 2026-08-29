# Section Match Confidence and Traceability — Design

**Status:** Approved for implementation

## Purpose

When two sections are paired across versions, the reviewer sees the result
but never the reasoning. That matters most in one specific case: the
heading was rewritten, and the tool paired the sections anyway because
their bodies matched.

```
'2.0 Scope'  ->  '2.0 Applicability'
```

Today this is presented as an ordinary heading change, indistinguishable
from a renumber. The reviewer has no way to know the tool made a judgment
call — or that the pairing might be wrong, and `Scope` was actually deleted
while `Applicability` is genuinely new.

This surfaces two things: **the match score on every matched row**, and **an
explicit statement when a heading was matched on content despite differing
substantially.**

## What exists today, verified

Six facts were confirmed against the live code before writing this spec.

**1. The match score is computed and thrown away.** `match_sections`
produces `SectionMatch(old_index, new_index, score)`, and `score` appears in
exactly one place: a debug `print` at `section_matching.py:47`. It never
reaches a `Change`.

**2. Every section-derived change hardcodes `confidence=1.0`.** All five
`Change` constructions in `section_structure.py` (lines 88, 177, 233, 262,
304) assert total certainty about a pairing they never checked.

**3. That fake value is persisted and exported.** `confidence` is a column
in `db.py`, a key in the JSON export, and a column in the CSV export
(`export.py:43`, `:73`, `:80`). The misleading `1.0` already reaches
documents that circulate.

**4. The frontend never displays `confidence` at all.** No occurrence
anywhere in `frontend/`. So the honest number has nowhere to appear until a
column exists.

**5. There is already a precedent for a real score.** `pipeline.py:125`
sets `confidence=mv.score` for both `moved_paragraph` and
`moved_table_content`. Carrying a match score in `confidence` is an
established pattern here, not an invention.

**6. `confidence` currently means three unrelated things.** Regex
detections default to `1.0` (deterministic, genuinely certain); LLM
classifications carry the model's self-assessment; moved paragraphs carry
an embedding similarity. A single column showing all of these would invite
a reviewer to read `0.29` as "less confident than `0.85`", when they are
different metrics entirely.

## The central finding

**The overall match score cannot distinguish a rewritten heading from a
renumbered one.** `_section_text` is `heading + body`, and bodies are long,
so the heading barely moves the number. Measured on the real corpus:

| combined score | change |
|---|---|
| 0.976 | `5.0 Equipment Qualification` → `5.0 Qualifying the Equipment` |
| 0.979 | `6.0 Documentation Review` → `6.5 Documentation Review` |

A substantial rewrite and a pure renumber, three thousandths apart. Any
design that keys off the overall score alone fails at the exact case this
feature exists for.

**Comparing the headings separately, with their numbers stripped, separates
them cleanly:**

| stripped similarity | change | verdict |
|---|---|---|
| 0.288 | `Scope` → `Applicability` | rewrite |
| 0.759 | `Equipment Qualification` → `Qualifying the Equipment` | rewrite |
| 1.000 | `Approval` → `Approval` (renumber) | not a rewrite |
| 1.000 | `Documentation Review` (renumber) | not a rewrite |
| 1.000 | `Materials and Equipment` (renumber) | not a rewrite |

Stripping the number is what makes this work. **With numbers included, a
pure renumber (`4.0 Approval` → `2.0 Approval`) scores 0.782 — lower than a
genuine rewrite at 0.869** — so the number actively inverts the signal.
Pure renumbers land at exactly 1.000 once stripped.

## Decision

### The `Match` column

A column in Detailed Changes, populated **only for rows produced by a
match**, blank everywhere else. One column, one meaning.

The blank is informative: it says no matching was involved. In particular
`section_added` and `section_deleted` are blank because those sections were
*unmatched* — there is no score to show, and inventing one would be the
same lie as the current `1.0`.

**No schema change.** The value is `Change.confidence`, which already
persists and exports. The frontend decides whether to show it from the
change type, following the `_WHOLE_SECTION_CHANGE_TYPES` pattern already in
`frontend/logic.py`:

```python
_MATCH_DERIVED_CHANGE_TYPES = {
    "section_heading_changed",
    "section_renumbered",
    "section_renumbered_cascade",
    "section_reordered",
    "moved_paragraph",
    "moved_table_content",
}
```

### The traceability clause

Appended to the existing `reason` — not replacing it, so the row still says
what changed before explaining why the pairing needed judgment:

```
Section heading changed. Headings differ substantially (similarity 0.29);
sections matched on content.
```

It appears only on `section_heading_changed` rows whose number-stripped
headings score **below 0.85**.

### The threshold

**0.85**, chosen from measured separation:

| range | cases |
|---|---|
| 0.106 – 0.759 | real rewrites (`Scope`→`Applicability`, `Approval`→`Deviation Handling`, `Quality Review`→`Final Disposition`, `Equipment Qualification`→`Qualifying the Equipment`) |
| 0.831 – 0.976 | trivial edits (`Scope`→`Scope and Purpose`, pluralisations, `and`→`&`) |

0.85 rather than 0.80 deliberately: it flags `Scope` → `Scope and Purpose`
(0.831), which is a genuine scope expansion, consistent with this project's
standing rule to over-report rather than hide. The gap between 0.759 and
0.831 is real but narrow, and these values come from one modest corpus — the
threshold is a single named constant so it can be retuned against real SOPs
without touching logic.

### Which rows get what

| Row | `Match` | Clause |
|---|---|---|
| `section_heading_changed` | ✓ | when stripped similarity < 0.85 |
| `section_renumbered` / `_cascade` | ✓ | — |
| `section_reordered` | ✓ | — |
| `section_added` / `section_deleted` | blank | — |
| `moved_paragraph` / `moved_table_content` | ✓ (already correct) | — |
| Regex- and LLM-derived content rows | blank | — |

## Design per component

### `backend/app/section_structure.py`

**Three of the five** `Change` constructions stop hardcoding
`confidence=1.0` and take the score from the `SectionMatch` they already
iterate: `detect_section_renumbering` (line 88),
`detect_section_reordering` (line 177), and
`detect_section_heading_changed` (line 304). All three already receive
`matches` and loop over them, so the score is in scope with no signature
change.

The other two are verified **unable** to supply a score and must not
change. `detect_section_added(inserted_indices, new_sections, ...)` and
`detect_section_deleted(deleted_indices, old_sections, ...)` never receive
`matches` at all — their sections are by definition unmatched. They keep
`confidence=1.0`, which is honest for them: the section's absence is a
fact, not a guess. Their rows render blank in the `Match` column because
their change types are absent from `_MATCH_DERIVED_CHANGE_TYPES`, not
because of their `confidence` value.

`detect_section_heading_changed` gains the clause. It already calls
`_split_heading_number` on both headings and already skips rows where only
the number changed, so the stripped text it needs is in scope at the point
the reason is built. It compares the two stripped strings with
`embed_texts` + `cosine_similarity_matrix` — the same machinery
`match_sections` uses — and appends the clause when the result falls below
the threshold constant.

Identical stripped headings short-circuit to `1.0` without embedding, since
`detect_section_heading_changed` cannot reach that state anyway and the
guard keeps the function honest if it is ever called directly.

### `frontend/logic.py`

`_MATCH_DERIVED_CHANGE_TYPES` as above, plus a formatter returning the
score to two decimals for those types and `""` for everything else.

### `frontend/pages/2_Detailed_Changes.py`

A `Match` key added to each row dict in all four group renderers
(headers/footers, body, tables). Each renderer builds plain dicts fed to
`st.table`, so this is one key per renderer and no structural change.

### Unaffected

`models.py`, `db.py`, `export.py`, `extraction.py`, `table_diff.py`,
`section_matching.py`, `llm_classifier.py`. No schema change, no migration:
`confidence` already exists end to end, and this only stops lying about its
value.

## Testing

- A section matched with a rewritten heading gets the clause, and the
  similarity in the clause matches the computed value.
- A pure renumber produces its `Match` score and **no** clause.
- A pluralised heading (measured 0.93) produces no clause — the guard
  against flagging every heading change.
- A heading rewrite at the boundary: a pair just below 0.85 flags, one just
  above does not.
- `section_added` and `section_deleted` leave `Match` blank in the rendered
  table.
- Regex- and LLM-derived rows leave `Match` blank.
- The real score reaches the CSV and JSON exports, replacing `1.0`.
- The Detailed Changes page renders with the new column across all four
  groups without exception.
- Corpus sweep: no change to which rows are produced — only their
  `confidence` values and, where applicable, their reason text.

## Out of Scope

- **Table structural rows.** `table_diff` also hardcodes `confidence=1.0`
  and its row/column matching does compute real scores. Extending this
  there is a straightforward follow-up, deliberately not bundled here.
- Changing how sections are matched, or the `0.6` matching threshold.
- Surfacing the LLM's self-reported confidence, which is a different metric
  and a separate question.
- Any reviewer workflow around low-confidence rows (filtering, sorting,
  sign-off gates).
