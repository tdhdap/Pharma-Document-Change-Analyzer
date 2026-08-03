# Table Change Source Labeling — Design

**Status:** Approved for implementation

## Purpose

A table cell that's added, deleted, or moved currently gets exactly the
same generic treatment as any other body paragraph — `added_paragraph`
with reason "New paragraph added.", `deleted_paragraph` with "Paragraph
removed.", `moved_paragraph` with "Paragraph moved from X to Y." — with
nothing anywhere indicating the change came from a table rather than
narrative body text. A reviewer looking at the change list has no way to
tell "this is a new row in the acceptance-criteria table" from "this is a
new sentence somewhere in the document."

## Decision

Add a `Change.source` field (`"Table"` or `"Body"`) shown as its own
column in the app, always visible regardless of change type — and
additionally rewrite the *wording* of the three generic structural change
types specifically when the source is a table, since those three carry no
other information about what kind of content changed.

**Why the wording rewrite is narrowly scoped to exactly these three
types:** `added_paragraph`, `deleted_paragraph`, and `moved_paragraph` are
already the least-specific labels in the system — the fallback for
"something structural happened, no finer classification exists." Rewriting
them to `added_table_content`/`deleted_table_content`/`moved_table_content`
loses no precision, because there was no more-specific alternative to
begin with. Every other type — `numeric_change`, `unit_change`,
`date_change`, and the 6 AI-classified semantic types
(`role_responsibility_change`, `reference_document_change`,
`qualitative_specification_change`, `process_sequence_change`,
`clarification_no_meaning_change`, `formatting_only`) — is already a
precise classification of *what* changed, and is left completely
untouched regardless of source. Overriding those with a generic "table"
label would be a genuine precision loss; overriding the three fallback
types is not, since they carry no comparable information today.

**Risk classification is unchanged.** The new type strings are not added
to `risk_rules.RISK_TABLE`, so they fall through to the same
`DEFAULT_RISK = "Medium"` their generic counterparts already receive —
this is a labeling change only, not a risk-classification change. (Noted
explicitly during design and confirmed with the user: if table-content
changes should carry different risk than generic paragraph adds/deletes,
that's a separate, not-yet-requested decision.)

**Scope: DOCX only**, matching the pattern of the two prior fixes in this
area. PDF and TXT paragraphs always default `from_table=False` — neither
format has an equivalent structural concept of "this text came from a
table cell." Header/footer paragraphs (not inside a table) stay
`from_table=False` too — their section name ("Page Header"/"Page Footer")
already makes their origin unambiguous, so no additional signal is needed
there.

## Design per component

### `backend/app/models.py`

- `Paragraph` gains `from_table: bool = False`, alongside the existing
  `allow_text_pattern_heading` field (independent of it — not derived from
  it, to avoid re-touching the already-shipped heading-fix logic).
- `Change` gains `source: str = "Body"`.

### `backend/app/extraction.py`

`_iter_docx_paragraphs` already threads `allow_text_pattern_heading`
through its recursive walk; it now threads `from_table` alongside it as a
second, independent parameter, defaulting to `False`. The table-recursion
branch hardcodes `from_table=True` for every paragraph inside a table cell
(mirroring how it already hardcodes `allow_text_pattern_heading=False`),
regardless of where that table sits (body, header, or footer) or what
value was passed in from the caller.

Unlike `allow_text_pattern_heading` (which defaults `True` and needs an
explicit `False` override at the header/footer call sites), `from_table`
needs no call-site overrides at all: its default (`False`) is already
correct for the top-level body walk, and also already correct for the
top-level header/footer walks, since neither a plain body paragraph nor a
plain header/footer paragraph is table content — only recursing into an
actual `DocxTable` ever flips it to `True`. So all 3 call sites in
`_extract_docx` (body, header, footer) need no changes to how they invoke
`_iter_docx_paragraphs` for this new parameter; they just need to unpack
the now-three-element yield and pass `from_table` through to
`_docx_paragraph_to_model`, which gains a matching `from_table: bool =
False` parameter threaded straight into the constructed `Paragraph`.

### `backend/app/pipeline.py`

Every place a `Change` is constructed computes `source` from the relevant
paragraph(s)' `from_table` field:

- Regex/AI-classified changes (`_build_paragraph_changes`): `source =
  "Table" if old_p.from_table or new_p.from_table else "Body"`. No
  change_type/reason rewriting here — every type this path produces
  (`numeric_change`, `unit_change`, `date_change`,
  `pending_llm_classification` → later one of the 6 AI-classified types)
  is precise and stays untouched.
- Moved paragraphs: `source` computed the same way from
  `mv.old_paragraph`/`mv.new_paragraph`; if `source == "Table"`,
  `change_type` becomes `"moved_table_content"` and the reason becomes
  `f"Table content moved from '{mv.old_section}' to '{mv.new_section}'."`
  instead of the generic wording.
- Deleted paragraphs: `source` from `p.from_table`; if `"Table"`,
  `change_type` becomes `"deleted_table_content"`, reason becomes "Table
  content removed."
- Added paragraphs: `source` from `p.from_table`; if `"Table"`,
  `change_type` becomes `"added_table_content"`, reason becomes "New table
  content added."

### `backend/app/export.py`

`to_json` and `to_csv` both explicitly enumerate `Change` fields by name
(confirmed by reading the file — neither uses a generic serializer), so
both need `source` added explicitly: one new dict key in `to_json`, one
new column in `to_csv`'s header row and per-row values.

### `frontend/pages/2_Detailed_Changes.py`

The `st.table(...)` call gains a `"Source": c["source"]` entry per row,
placed right after `"Section"` (Section says *where* in the document;
Source says *what kind* of content it was).

### Unaffected

`sectioning.py`, `section_matching.py`, `paragraph_diff.py`,
`move_reconciliation.py`, `regex_detectors.py`, `llm_classifier.py`,
`risk_rules.py` — confirmed no changes needed anywhere in the
classification/risk pipeline, only in how `Change` objects are labeled
after classification already happened.
`frontend/pages/1_Change_Summary.py` (aggregate counts only, no per-change
display) and `frontend/pages/3_Review_and_Export.py` (displays `section`/
`reason`/risk/reviewer fields, no `change_type` column) — confirmed by
reading both files, neither needs a change.
`frontend/logic.py`'s `filter_changes` and `frontend/api_client.py` — both
generic enough (operate on whatever fields are present) to need no change.

## Testing

- A table-cell paragraph deleted between v1/v2 (row removed): assert
  `Change.source == "Table"`, `change_type == "deleted_table_content"`,
  reason mentions table content, not "Paragraph removed."
- A table-cell paragraph added (new row): assert `source == "Table"`,
  `change_type == "added_table_content"`.
- A table cell that moves between two matched sections along with other
  reconciled content: assert `source == "Table"`,
  `change_type == "moved_table_content"`.
- A table cell with a precise regex-classified change (e.g. a numeric
  value changed): assert `source == "Table"` but `change_type` stays
  `"numeric_change"` — proves precise types are never overridden.
- A body paragraph (not from a table) added/deleted/moved: assert `source
  == "Body"` and `change_type` stays the generic
  `added_paragraph`/`deleted_paragraph`/`moved_paragraph` — regression
  guard proving body-paragraph behavior is completely unaffected.
- `export.py`'s `to_json`/`to_csv`: assert the `source` field/column is
  present and correctly populated for a comparison containing both table
  and body changes.
- Full backend suite re-run to confirm no regressions.
- Manual check in the running app (`2_Detailed_Changes.py`) against the
  real `TableHeaderFooterDemo_v1.docx`/`_v2.docx` pair: confirm the new
  "Source" column shows "Table" for the table-cell changes and "Body" for
  everything else, and that the added-row entries now read
  "added_table_content" / "New table content added." instead of the
  generic wording.

## Out of Scope

- Any change to risk classification for table-sourced changes — labeling
  only, as stated above.
- PDF/TXT table detection — no structural equivalent exists.
- A "Filter by source" dropdown in the frontend — not requested; the
  Source column alone satisfies the stated goal of making table origin
  visible. Can be added later if wanted.
- Distinguishing header/footer as their own `source` values — their
  section name already makes this unambiguous.
