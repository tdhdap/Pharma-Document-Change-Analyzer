"""Generate FullCoverageDemo_v1.docx / _v2.docx.

The pair is built to produce every deterministic change type the analyzer can
emit. Run from the repository root:

    python scripts/generate_full_coverage_docs.py

The OOXML helpers below (text box, footnote reference, footnotes part) are
deliberate copies of the private helpers in backend/tests/test_extraction.py.
Importing private names from a test module into a script is fragile, and
lifting them into a shared module would churn a large green test file for no
behavioural gain.

Two things Word rejects, both guarded here:
  * a paragraph appended after <w:sectPr>, which must be the last child of
    <w:body> - use body.insert_element_before(p, "w:sectPr")
  * a <wp:inline> missing <wp:extent> or <wp:docPr>
"""

import os

from docx import Document

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "test-documents", "docx")

# Section layout. The insertion (2.0 Responsibilities, v2 only) sits ABOVE the
# cascade-affected sections and the deletion (Definitions) BELOW them, so the net
# shift for the cascade sections is exactly +1. Sections below the deletion cancel
# out and stay put. "9.0 Records" takes +2 against an expected +1, so it is
# reported as a deliberate renumber rather than a cascade.
V1_SECTIONS = [
    ("1.0 Purpose", [
        "This procedure describes tablet compression and release testing.",
        "It applies to all commercial batches manufactured at Site B.",
    ]),
    ("2.0 Scope", [
        "Covers in-process control, finished product testing, and release.",
        "Excludes stability testing, which is covered by SOP-QA-118.",
    ]),
    ("3.0 Equipment", [
        "Compression is performed on the rotary press listed below.",
    ]),
    ("4.0 Sampling", [
        "Samples are drawn at the start, middle, and end of each run.",
        "A retained sample of 30 tablets is held for each batch.",
        "Sampling tools are cleaned between batches.",
    ]),
    ("5.0 Procedure", [
        "Compression force shall be maintained at 18 kN plus or minus 2 kN.",
        "Record the force reading every 30 minutes during the run.",
    ]),
    ("6.0 Acceptance Criteria", [
        "Assay shall be 95.0 percent to 105.0 percent of label claim.",
    ]),
    ("7.0 Deviations", [
        "Deviations are recorded in the quality management system.",
    ]),
    ("8.0 Training", [
        "Operators are trained before independent operation.",
    ]),
    ("9.0 Records", [
        "Batch records are retained for seven years.",
    ]),
    ("10.0 Definitions", [
        "In-process control means testing performed during manufacture.",
        "Retained sample means material held for future examination.",
        "Release means the formal decision to make a batch available.",
    ]),
    ("11.0 Approval", [
        "This procedure is approved by the QC Manager.",
    ]),
    ("12.0 References", [
        "Refer to the equipment manual for calibration intervals.",
    ]),
]

# v2 differences from v1, and nothing else:
#   - Insert "2.0 Responsibilities" (2 paragraphs) at index 1, renumbering
#     "2.0 Scope" onward.
#   - Rename "2.0 Scope" to "3.0 Applicability" -- a substantial rewording, so
#     section matching pairs it on body content and the confidence clause
#     fires. Body kept intact so the content-similarity match stays strong.
#   - Delete "10.0 Definitions" entirely (3 paragraphs; its table arrives in
#     Task 2).
#   - Cascade (+1 each, side effect of the Responsibilities insertion above
#     them): "3.0 Equipment" -> "4.0 Equipment", "4.0 Sampling" ->
#     "5.0 Sampling", "6.0 Acceptance Criteria" -> "7.0 Acceptance Criteria",
#     "7.0 Deviations" -> "8.0 Deviations", "8.0 Training" -> "9.0 Training".
#   - Deliberate renumber: "9.0 Records" -> "11.0 Records" (+2 against an
#     expected +1).
#   - Move: "5.0 Procedure" relocates to after "Training", becoming
#     "10.0 Procedure", AND its compression force changes from 18 kN to
#     20 kN -- the move-must-not-hide-an-edit case.
#   - Content edits in otherwise stable sections: add one paragraph to
#     "1.0 Purpose" (added_paragraph); delete the third "4.0 Sampling"
#     paragraph (deleted_paragraph); change "95.0 percent to 105.0 percent"
#     to "98.0 percent to 102.0 percent" in Acceptance Criteria
#     (numeric_change); change "seven years" to "ten years" in Records;
#     change a date and a unit in "12.0 References" (date_change,
#     unit_change) -- v1's References sentence carries neither, so both
#     detectors fire on the before/after-empty-to-populated transition.
#   - Move a paragraph between sections: the retained-sample sentence moves
#     from Sampling to Acceptance Criteria (moved_paragraph).
V2_SECTIONS = [
    ("1.0 Purpose", [
        "This procedure describes tablet compression and release testing.",
        "It applies to all commercial batches manufactured at Site B.",
        "This revision also covers electronic batch record entries for Site B lines.",
    ]),
    ("2.0 Responsibilities", [
        "The Production Supervisor is responsible for line clearance before each run.",
        "The Quality Assurance Manager is responsible for final batch disposition.",
    ]),
    ("3.0 Applicability", [
        "Covers in-process control, finished product testing, and release.",
        "Excludes stability testing, which is covered by SOP-QA-118.",
    ]),
    ("4.0 Equipment", [
        "Compression is performed on the rotary press listed below.",
    ]),
    ("5.0 Sampling", [
        "Samples are drawn at the start, middle, and end of each run.",
    ]),
    ("7.0 Acceptance Criteria", [
        "Assay shall be 98.0 percent to 102.0 percent of label claim.",
        "A retained sample of 30 tablets is held for each batch.",
    ]),
    ("8.0 Deviations", [
        "Deviations are recorded in the quality management system.",
    ]),
    ("9.0 Training", [
        "Operators are trained before independent operation.",
    ]),
    ("10.0 Procedure", [
        "Compression force shall be maintained at 20 kN plus or minus 2 kN.",
        "Record the force reading every 30 minutes during the run.",
    ]),
    ("11.0 Records", [
        "Batch records are retained for ten years.",
    ]),
    ("11.0 Approval", [
        "This procedure is approved by the QC Manager.",
    ]),
    ("12.0 References", [
        "Refer to the equipment manual, effective 15 Mar 2024, for calibration at a tolerance of 2°C.",
    ]),
]


def _add_sections(doc, sections):
    for heading, paragraphs in sections:
        doc.add_heading(heading, level=1)
        for text in paragraphs:
            doc.add_paragraph(text)


def build_v1(path):
    doc = Document()
    _add_sections(doc, V1_SECTIONS)
    doc.save(path)


def build_v2(path):
    doc = Document()
    _add_sections(doc, V2_SECTIONS)
    doc.save(path)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    build_v1(os.path.join(OUT_DIR, "FullCoverageDemo_v1.docx"))
    build_v2(os.path.join(OUT_DIR, "FullCoverageDemo_v2.docx"))
    print(f"wrote FullCoverageDemo_v1.docx and _v2.docx to {OUT_DIR}")


if __name__ == "__main__":
    main()
