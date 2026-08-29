# FullCoverageDemo — Expected Results

Generated from an actual comparison of `FullCoverageDemo_v1.docx` against
`FullCoverageDemo_v2.docx`, with the LLM classifier stubbed. Every row below is
transcribed output, not a prediction.

Regenerate the documents with:

```bash
python scripts/generate_full_coverage_docs.py
```

The pair is asserted by `backend/tests/test_full_coverage_corpus.py`.

## Summary

`total=56 high=7 med=36 low=0 info=13 add=1 del=1 ren=1 num=2 casc=6 mov=2`

## Change type counts

| Change type | Count |
|---|---|
| `added_paragraph` | 1 |
| `added_table_content` | 8 |
| `date_change` | 2 |
| `deleted_paragraph` | 1 |
| `deleted_table_content` | 8 |
| `moved_paragraph` | 1 |
| `moved_table_content` | 7 |
| `numeric_change` | 4 |
| `section_added` | 1 |
| `section_deleted` | 1 |
| `section_heading_changed` | 1 |
| `section_renumbered` | 2 |
| `section_renumbered_cascade` | 6 |
| `section_reordered` | 2 |
| `table_cell_merge_changed` | 1 |
| `table_column_added` | 1 |
| `table_column_deleted` | 1 |
| `table_column_moved` | 1 |
| `table_row_added` | 1 |
| `table_row_deleted` | 1 |
| `table_row_moved` | 1 |
| `unclassified` | 3 |
| `unit_change` | 1 |

The seven table structure types each fire **exactly once** by design — every table
in the fixture changes in one way only. A count above one means a table started
doing two things, usually a row edit large enough to drop the row below the 0.85
match threshold and turn it into a delete+add pair.

`unclassified` rows are omitted below. They are an artifact of stubbing the
classifier — pending rows fall back when the stub returns nothing — not an
intended detection.

## Every row

| Section | Change Type | Old Text | New Text | Risk |
|---|---|---|---|---|
| 1.0 Purpose | `added_paragraph` | — | This revision also covers electronic batch r... | Medium |
| 1.0 Purpose | `added_table_content` | — | Storage Condition | Medium |
| 1.0 Purpose | `added_table_content` | — | Container | Medium |
| 1.0 Purpose | `added_table_content` | — | 25 C / 60 percent RH | Medium |
| 1.0 Purpose | `added_table_content` | — | 24 months | Medium |
| 1.0 Purpose | `added_table_content` | — | HDPE bottle | Medium |
| 1.0 Purpose | `added_table_content` | — | 30 C / 75 percent RH | Medium |
| 1.0 Purpose | `added_table_content` | — | 6 months | Medium |
| 1.0 Purpose | `added_table_content` | — | Blister pack | Medium |
| 12.0 References | `date_change` | Refer to the equipment manual for calibratio... | Refer to the equipment manual, effective 15 ... | Medium |
| 12.0 References | `date_change` | Rev 3, dated 10 Jan 2022 | Rev 4, dated 15 Mar 2024 | Medium |
| 4.0 Sampling | `deleted_paragraph` | Sampling tools are cleaned between batches. | — | Medium |
| 7.0 Deviations | `deleted_table_content` | Carrier | — | Medium |
| 7.0 Deviations | `deleted_table_content` | Transit Time | — | Medium |
| 7.0 Deviations | `deleted_table_content` | Site B to Warehouse 4 | — | Medium |
| 7.0 Deviations | `deleted_table_content` | Cold chain courier | — | Medium |
| 7.0 Deviations | `deleted_table_content` | 48 hours | — | Medium |
| 7.0 Deviations | `deleted_table_content` | Warehouse 4 to Depot | — | Medium |
| 7.0 Deviations | `deleted_table_content` | Ambient freight | — | Medium |
| 7.0 Deviations | `deleted_table_content` | 72 hours | — | Medium |
| 4.0 Sampling -> 7.0 Acceptance... | `moved_paragraph` | A retained sample of 30 tablets is held for ... | A retained sample of 30 tablets is held for ... | Medium |
| 6.0 Acceptance Criteria -> 7.0... | `moved_table_content` | Content Uniformity | Content Uniformity | Medium |
| 6.0 Acceptance Criteria -> 7.0... | `moved_table_content` | AV less than or equal to 15 | AV less than or equal to 15 | Medium |
| 6.0 Acceptance Criteria -> 7.0... | `moved_table_content` | USP <905> | USP <905> | Medium |
| 8.0 Training -> 1.0 Purpose | `moved_table_content` | Duration | Duration | Medium |
| 9.0 Records -> 11.0 Records | `moved_table_content` | Archive Room A | Archive Room A | Medium |
| 9.0 Records -> 11.0 Records | `moved_table_content` | Archive Room B | Archive Room B | Medium |
| 9.0 Records -> 11.0 Records | `moved_table_content` | Storage Location | Storage Location | Medium |
| 12.0 References | `numeric_change` | Refer to the equipment manual for calibratio... | Refer to the equipment manual, effective 15 ... | High |
| 12.0 References | `numeric_change` | Rev 3, dated 10 Jan 2022 | Rev 4, dated 15 Mar 2024 | High |
| 5.0 Procedure | `numeric_change` | Compression force shall be maintained at 18 ... | Compression force shall be maintained at 20 ... | High |
| 6.0 Acceptance Criteria | `numeric_change` | Assay shall be 95.0 percent to 105.0 percent... | Assay shall be 98.0 percent to 102.0 percent... | High |
| 2.0 Responsibilities | `section_added` | — | 2.0 Responsibilities The Production Supervis... | High |
| 10.0 Definitions | `section_deleted` | 10.0 Definitions In-process control means te... | — | High |
| 2.0 Scope | `section_heading_changed` | 2.0 Scope | 3.0 Applicability | Medium |
| 5.0 Procedure | `section_renumbered` | 5.0 Procedure | 10.0 Procedure | Informational |
| 9.0 Records | `section_renumbered` | 9.0 Records | 11.0 Records | Informational |
| 2.0 Scope | `section_renumbered_cascade` | 2.0 Scope | 3.0 Applicability | Informational |
| 3.0 Equipment | `section_renumbered_cascade` | 3.0 Equipment | 4.0 Equipment | Informational |
| 4.0 Sampling | `section_renumbered_cascade` | 4.0 Sampling | 5.0 Sampling | Informational |
| 6.0 Acceptance Criteria | `section_renumbered_cascade` | 6.0 Acceptance Criteria | 7.0 Acceptance Criteria | Informational |
| 7.0 Deviations | `section_renumbered_cascade` | 7.0 Deviations | 8.0 Deviations | Informational |
| 8.0 Training | `section_renumbered_cascade` | 8.0 Training | 9.0 Training | Informational |
| 5.0 Procedure | `section_reordered` | 5.0 Procedure | 10.0 Procedure | Informational |
| Text Box 2 (8.0 Training, para... | `section_reordered` | Text Box 2 (8.0 Training, paragraph 1) | Text Box 1 (9.0 Training, paragraph 1) | Informational |
| Table 9 | `table_cell_merge_changed` | Approved By | Approved By Reviewed By | Informational |
| Table 6 | `table_column_added` | — | Reported By / Line Supervisor / QA Associate | Medium |
| Table 7 | `table_column_deleted` | Duration / 2 hours / 4 hours | — | Medium |
| Table 8 | `table_column_moved` | Storage Location / Archive Room A / Archive ... | Storage Location / Archive Room A / Archive ... | Informational |
| Table 3 | `table_row_added` | — | Coating Pan / O'Hara Labcoat 24 / 25 kg batc... | Medium |
| Table 4 | `table_row_deleted` | Middle of run / 10 tablets / Once per batch | — | Medium |
| Table 5 | `table_row_moved` | Content Uniformity / AV less than or equal t... | Content Uniformity / AV less than or equal t... | Informational |
| 12.0 References | `unit_change` | Refer to the equipment manual for calibratio... | Refer to the equipment manual, effective 15 ... | High |

## Anchoring labels

| Version | Labels |
|---|---|
| v1 | `Text Box 1 (5.0 Procedure, paragraph 1)`, `Text Box 2 (8.0 Training, paragraph 1)`, `Footnote 1 (5.0 Procedure, paragraph 1)` |
| v2 | `Text Box 1 (9.0 Training, paragraph 1)`, `Text Box 2 (10.0 Procedure, paragraph 1)`, `Footnote 1 (10.0 Procedure, paragraph 1)` |

The ordinals swap between versions because Procedure moves below Training. That is
exactly why the anchor matters: `Text Box 1` means different things in the two
documents, while the section name does not.

## LLM-dependent types — not asserted

These six are the model's judgement, not a function of document content. The pair
contains wording written to invite each, but the label actually returned may
differ between runs and between model versions, so no test asserts them.

| Change type | Wording written to invite it |
|---|---|
| `role_responsibility_change` | Approval moves from the QC Manager to the QA Manager |
| `reference_document_change` | The referenced equipment manual revision changes |
| `qualitative_specification_change` | Sampling wording tightened |
| `process_sequence_change` | Recording interval reworded |
| `clarification_no_meaning_change` | Purpose wording expanded without changing meaning |
| `formatting_only` | Punctuation and casing adjustments |

`unclassified` and `pending_llm_classification` are unreachable by authoring: the
first only appears when an LLM call fails, the second is an internal placeholder
the pipeline overwrites.
