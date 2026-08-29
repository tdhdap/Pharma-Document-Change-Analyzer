# Full-Coverage Test Documents — Design

**Status:** Approved for implementation

## Purpose

Eight features were built across this project — moved-content detection,
section content summaries, cascading-vs-deliberate renumbering, table
structure diffing, text box and footnote anchoring, section match
confidence, and the structural change summary. No single document exercises
them together, and one detection type (`section_renumbered_cascade`) is
produced by **no** document in the corpus at all.

This adds one DOCX pair that provably produces every deterministic change
type the system can emit, so the whole detector stack can be regression-
tested and demonstrated from a single comparison.

## What the system can emit, verified

Enumerated from the source, not from memory. **28 authorable change types**
in two groups that must be treated differently, plus two the document
cannot reach.

**22 deterministic** — produced by document content alone, identical on
every run, no API call:

```
numeric_change            unit_change              date_change
section_added             section_deleted          section_heading_changed
section_renumbered        section_renumbered_cascade
section_reordered         moved_paragraph          moved_table_content
added_paragraph           deleted_paragraph
added_table_content       deleted_table_content
table_row_added           table_row_deleted        table_row_moved
table_column_added        table_column_deleted     table_column_moved
table_cell_merge_changed
```

**6 LLM-derived** — `role_responsibility_change`,
`reference_document_change`, `qualitative_specification_change`,
`process_sequence_change`, `clarification_no_meaning_change`,
`formatting_only`. `classify_changes_batch` sends one batched request per
comparison, so quota is not the constraint; **reproducibility is**. Text
written to invite one label may be returned as another, and the mapping
shifts when the upstream model changes.

**Two types are unreachable by authoring.** `unclassified` is produced only
when the LLM call fails (`_fallback`), and `pending_llm_classification` is
an internal placeholder the pipeline overwrites before the result is
returned. Neither can be caused by document content, so neither is a
coverage target.

22 + 6 = 28 authorable types; these two bring the source total to 30.

### The decision this forces

The pair **guarantees the 22 deterministic types**. The 6 LLM types get
purpose-written sentences and are documented as "LLM-dependent, not
asserted". An automated test that pinned an LLM label would fail randomly
for reasons unrelated to this codebase.

## Deliverables

**1. `test-documents/docx/FullCoverageDemo_v1.docx` and `_v2.docx`.**

**2. A committed generator script** that builds both from scratch.

`scripts/generate_test_documents.py` already exists (committed in `3bbd80b`)
and generates the A, B, C1, C2 and SOP pairs as both DOCX and PDF, each
followed by a `validate()` call that re-extracts the file and checks its
heading sequence. **That validate-after-generate pattern is the one to
follow.** It is section-only, though — it has no notion of tables, text
boxes or footnotes — so this pair needs its own generator rather than a few
more scenario constants.

The six `*Demo` pairs in the corpus have no generator at all and are opaque
binaries. This new fixture is the most intricate of the set and must not
join them: when a detector changes, the fixture has to be edited, and that
requires seeing how it was built.

**3. An automated regression test** asserting all 22 types appear in the
comparison, with `classify_changes_batch` stubbed so it neither spends
quota nor introduces nondeterminism.

**4. An expected-results table** documenting every row the comparison
produces, including the LLM-dependent ones marked as such.

## Document structure

Roughly 13 sections and 10 small (3x3) tables, written as a pharmaceutical
SOP consistent with the existing corpus.

### One purpose per table

Tables are deliberately single-purpose: `T1` row added, `T2` row deleted,
`T3` row moved, `T4` column added, `T5` column deleted, `T6` column moved,
`T7` merge changed, `T8` cell content only (no structural change). Two
further tables live inside the added and deleted sections.

Combining axes within one table would exercise the row/column *interaction*
rather than each detector. That interaction is where this project's
defects have concentrated — a column change reshuffles row matching, which
required the two-pass restructure, and an introduced merge empties a column
and faked a delete+add. Those interactions deserve their own fixtures
later; this pair proves each detector works.

### Suppression forces separation

The tool suppresses per-cell rows for a structurally added or deleted row,
and suppresses `deleted_paragraph` for paragraphs inside a deleted section.
So:

- `added_table_content` / `deleted_table_content` are proved in `T8`, which
  has no structural change.
- `added_paragraph` / `deleted_paragraph` are proved in sections that are
  otherwise stable.
- The deleted section carries **3 paragraphs and 1 table**, so its summary
  reads exactly `3 paragraphs, 1 table.` — verified as the live output
  format of `_summarize_section_content`.

### The cascade arithmetic

`section_renumbered_cascade` fires only when the number shift equals the
net count of top-level numbered sections inserted minus deleted *above*
that section. A document that adds one section and deletes another above
the same section nets zero and produces **no renumbering at all**.

The layout therefore places the **insertion above** the cascade-affected
sections and the **deletion below** them, and gives one further section a
number the arithmetic cannot explain. Verified against the live detector:

```
v1: 1.0 Purpose  2.0 Scope  3.0 Equipment  4.0 Records  5.0 Legacy Annex
v2: 1.0 Purpose  2.0 Scope  3.0 Responsibilities  4.0 Equipment  6.0 Records
    (inserted at index 2; Legacy Annex deleted)

section_renumbered_cascade  '3.0 Equipment' -> '4.0 Equipment'
    "...as a side effect of 1 section added above it; wording unchanged."
section_renumbered          '4.0 Records'   -> '6.0 Records'
```

`Equipment` shifts +1, matching the expected +1, so it is mechanical.
`Records` shifts +2 against an expected +1, so it stays deliberate. This is
the type no existing document produces, and it is the main reason this
fixture exists.

### Per-feature coverage

| Feature | How the pair proves it |
|---|---|
| Move must not hide edits | One section moves **and** has a numeric edit inside; both rows must appear |
| Section content summary | Deleted section holds 3 paragraphs + 1 table; added section holds paragraphs + a table |
| Cascade vs deliberate | The arithmetic above |
| Table structure | `T1`–`T7`, one detector each |
| Text box anchoring | Two text boxes in **different** sections, so labels differ by anchor, not just ordinal |
| Footnote anchoring | A footnote referenced from a known paragraph of a known section |
| Match confidence | One heading substantially reworded, matched on body content, so the clause fires |
| Structural summary | All six metrics non-zero, including `Sections Cascaded` |

## Word must open the files

Both earlier demo pairs were rejected by Word, for two distinct causes now
known:

1. A text-box paragraph appended with `body.append(p)` lands **after**
   `<w:sectPr>`, which must be the last child of `<w:body>`. Use
   `body.insert_element_before(p, "w:sectPr")`.
2. A `<wp:inline>` missing its required `<wp:extent>` and `<wp:docPr>`.
   The generator reuses the wrapper python-docx itself emits for a real
   inline picture rather than hand-writing one.

**Opening both files in Word is an explicit manual acceptance step.**
pytest cannot detect this class of corruption — both rejected files parsed
fine under python-docx.

## Testing

- The comparison produces **all 22 deterministic types**, asserted as a set
  difference so a failure names exactly which type is missing.
- The moved-and-modified section yields both its move row and its content
  row — the central false-negative guard.
- The deleted section's summary reads `3 paragraphs, 1 table.`
- Exactly one `section_renumbered_cascade` and one `section_renumbered`,
  each on the intended heading.
- The two text box labels carry **different** section anchors.
- The footnote label names the section and paragraph it belongs to.
- The reworded heading's row carries the "matched on content" clause.
- All six structural summary counts are non-zero.
- Both files load through `extract_text` without error, and re-comparing v1
  against itself produces zero changes.
- The generator is deterministic: running it twice produces documents that
  compare identically.

## Out of Scope

- Guaranteeing the 6 LLM-derived types, for the reproducibility reason
  above.
- `unclassified`, which is unreachable by authoring.
- Header/footer and PDF/TXT coverage; those paths have their own fixtures.
- Regenerating or replacing the existing corpus documents. This pair is
  additive, and the existing pairs stay as they are.
- Table fixtures for row/column *interactions* (a column change plus a row
  change in one table). Noted above as deserving their own fixtures.
