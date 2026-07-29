# AI-Assisted Pharmaceutical Document Change Analyzer — Design

**Date:** 2026-07-29
**Status:** Approved for planning

## 1. Purpose & Scope

A web app that compares two versions of a pharmaceutical document (SOP, specification,
analytical method, protocol, report) and produces a categorized, risk-scored change report
with source evidence, so a reviewer doesn't have to manually diff the documents.

This is an **internship deliverable / demo**: the design favors a lean, working end-to-end
prototype over production hardening (no auth, no multi-user support, no elaborate audit
logging). One structural concession is made toward future real-world use: reviewer edits
are stored alongside (not overwriting) the original AI classification, since that's cheap
to do now and expensive to retrofit later.

Supported input for MVP: text-based PDF, DOCX, TXT. Scanned/OCR documents are explicitly
out of scope (phase 2, per the source outline).

## 2. Architecture

Two-service Docker Compose app:

- **`ui` (Streamlit)** — all UI pages. Talks to the API over HTTP only; holds no business
  logic and never touches SQLite directly.
- **`api` (FastAPI)** — text extraction, section matching, diffing, classification, risk
  rules, SQLite persistence.
- **SQLite** — a single file on a shared Docker volume; no separate DB container.
- **Gemini API** — called from the backend only, for the subset of change types that
  need semantic judgment (see §4). Requires `GEMINI_API_KEY` via `.env` (git-ignored).

Comparison runs **synchronously**: `POST /compare` runs the full pipeline within the
request and returns the finished result. Documents are small (a few pages), so this avoids
building a job queue / status-polling loop that wouldn't earn its keep at this scale.

No authentication for the MVP — single-user local/demo tool.

## 3. Document Processing Pipeline

1. **Extraction.** PyMuPDF for PDF (page-anchored), python-docx for DOCX
   (paragraph-anchored), plain read for TXT. Every paragraph retains a reference back to
   its page (PDF) or paragraph index (DOCX/TXT) for citation in the final report.

2. **Sectioning.** Primary heuristic: regex over numbered/heading-style lines
   (pharma SOPs are almost always numbered, e.g. `5.2 Sample Preparation`) splits each
   document into `(heading, body_paragraphs)` sections. If no headings are detected
   (e.g. unstructured TXT), fall back to blank-line-delimited paragraph groups as
   pseudo-sections. Every change is always attributable to a `section` label.

3. **Section matching.** Embed each section (heading + body) with a local
   sentence-transformers model (no per-call API cost, since this runs on every section
   pair). Build a cosine-similarity matrix between old and new sections; greedily match
   best pairs above a similarity threshold, starting at **0.5** (tunable against real
   fixtures during implementation — low enough to tolerate reworded headings, high enough
   to avoid matching unrelated sections). Unmatched old sections are deleted sections;
   unmatched new sections are inserted sections.

4. **Within-section diff.** `difflib.SequenceMatcher` over paragraphs within each matched
   section pair, producing equal / replace / delete / insert opcodes.

5. **Move reconciliation.** Collect every orphaned delete/insert paragraph across the
   *entire* document (not just one section pair), embed them, and cross-match old-orphans
   against new-orphans. A pair scoring above a high similarity threshold, starting at
   **0.85**, is reclassified as a **moved paragraph** change (old section → new section) instead of a
   separate delete + insert. Remaining orphans stay as plain adds/deletes.

6. **Regex pass.** Every remaining modified/added/deleted paragraph is checked against
   regex filters for numbers, units, and dates, producing `numeric_change` /
   `unit_change` / `date_change` tags with a templated reason (e.g. "value narrowed from
   X to Y") and confidence 1.0 (deterministic).

7. **LLM pass (batched).** Anything unresolved after step 6 — a reworded paragraph, a
   changed responsibility, a changed reference — is bundled into **one Gemini call per
   comparison** (not one call per change), classifying each into one of:
   `role_responsibility_change`, `reference_document_change`,
   `qualitative_specification_change`, `process_sequence_change`,
   `clarification_no_meaning_change`, `formatting_only` — plus a one-sentence reason and
   a self-reported confidence. Regex stays authoritative for numeric changes; the LLM only
   handles what regex genuinely can't.

## 4. Classification & Risk Rules

Every change gets exactly one `change_type`, sourced from one of:

| Source | change_types | Confidence |
|---|---|---|
| difflib opcodes | added / deleted / modified / moved paragraph | 1.0 |
| Regex | numeric_change, unit_change, date_change | 1.0 |
| Move reconciliation | (tags a paragraph as moved) | cosine similarity score |
| Gemini batch call | role_responsibility_change, reference_document_change, qualitative_specification_change, process_sequence_change, clarification_no_meaning_change, formatting_only | LLM self-reported score |

Risk is assigned from a **fixed rule table** keyed on `change_type` — this is the source
of truth for risk even when the LLM did the classifying; the LLM picks the *type*, the
table picks the *risk*. This keeps risk assignment auditable and consistent.

| change_type | risk_level |
|---|---|
| numeric_change, unit_change | High |
| process_sequence_change | High |
| qualitative_specification_change | High |
| role_responsibility_change | Medium |
| reference_document_change | Medium |
| date_change | Medium |
| clarification_no_meaning_change | Low |
| formatting_only | Informational |
| added / deleted / moved paragraph (no other tag applies) | Medium (default — nothing else classified it, so it needs a human look) |

Reason text is templated for deterministic types, LLM-authored for the semantic types.

## 5. Data Model

SQLite, three tables:

```
documents
  id, filename, file_type, storage_path, uploaded_at

comparisons
  id (comparison_id), old_document_id, new_document_id, created_at

changes
  id (change_id), comparison_id, section,
  change_type, old_text, new_text,
  old_page, new_page, confidence,
  ai_risk_level,        -- assigned by the pipeline
  reviewer_risk_level,  -- nullable; set only if a reviewer overrides
  reason,
  reviewer_comment, accepted (bool)
```

`ai_risk_level` and `reviewer_risk_level` are kept as separate columns so the original
classification is never lost when a reviewer edits it.

## 6. API

- `POST /documents` — upload a file, extract text, return `document_id` + extracted text
- `POST /compare` — `{old_document_id, new_document_id}` → runs the full pipeline
  synchronously, persists, returns the full comparison (matches the outline's schema)
- `GET /comparisons/{id}` — refetch a comparison
- `PATCH /changes/{change_id}` — reviewer edits: `reviewer_risk_level`,
  `reviewer_comment`, `accepted`
- `GET /comparisons/{id}/export?format=csv|json` — export

## 7. Streamlit Pages

- **Page 1 — Upload & Compare:** upload old/revised documents, display filenames +
  extracted text, "Compare" button with a spinner during synchronous processing.
- **Page 2 — Change Summary:** total/high/medium/low/informational counts as metrics.
- **Page 3 — Detailed Changes:** filterable table (section, old text, new text, change
  type, risk, reason) with filters on risk / section / change type.
- **Page 4 — Review & Export:** editable table (reviewer risk override, comment,
  accepted toggle) via `st.data_editor`, each edit calling `PATCH /changes/{id}`; export
  buttons for CSV/JSON.

Current `comparison_id` is held in `st.session_state` across pages.

## 8. Deployment & Config

```
services:
  api:
    build: ./backend
    volumes: [data:/data]
    environment: [GEMINI_API_KEY, DB_PATH=/data/app.db]
    ports: ["8000:8000"]

  ui:
    build: ./frontend
    environment: [API_BASE_URL=http://api:8000]
    ports: ["8501:8501"]
    depends_on: [api]

volumes: { data: }
```

`GEMINI_API_KEY` comes from a local `.env` (git-ignored). The sentence-transformers
embedding model is downloaded into the `api` image at build time. Repo layout:
`backend/` (FastAPI app + pipeline modules), `frontend/` (Streamlit pages), each with
its own `Dockerfile` + `requirements.txt`, plus root `docker-compose.yml` and
`.env.example`.

## 9. Error Handling

- Unsupported file type → `400` with a clear message surfaced in Streamlit.
- No headings detected → falls back to paragraph-group pseudo-sections (never a hard
  failure).
- Gemini call fails/times out/rate-limits → affected changes fall back to
  `change_type: unclassified`, `risk_level: Medium`, `confidence: 0`, reason:
  "Automatic classification unavailable — needs manual review." The comparison still
  completes and returns everything else.

## 10. Testing

- Unit tests per pipeline stage: extraction (fixture PDF/DOCX/TXT), sectioning regex,
  embedding-based section matching (fixture with a renamed heading), regex detectors
  (numeric/unit/date), risk rule table.
- One end-to-end integration test using the outline's own Version 1 / Version 2 example
  (assay range, storage condition, QC→QA manager) asserting the pipeline reproduces the
  three expected changes at the expected risk levels — doubles as a regression test and
  a spec conformance check.
- LLM-dependent tests use a mocked Gemini response — no live API calls in the test suite.

## 11. Explicitly Out of Scope (MVP)

- Scanned/OCR document support (phase 2 per outline)
- Authentication / multi-user support
- Background job processing / progress polling
- Full audit-log history of every edit (only current AI vs. reviewer risk is kept, not a
  timeline of changes)
