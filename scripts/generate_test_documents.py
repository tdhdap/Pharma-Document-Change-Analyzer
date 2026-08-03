"""Generate DOCX/PDF test fixtures for the doc-change-analyzer's 5 existing
TXT scenarios (A, B, C1, C2, SOP). Each scenario is assigned one
heading-detection convention (structural / all_caps / mixed / font_size /
none) so the fixtures double as isolation tests for the multi-signal
heading detection built in
docs/superpowers/plans/2026-07-31-multi-signal-heading-detection.md.

Run: python scripts/generate_test_documents.py
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

from docx import Document
from docx.shared import Pt
import fitz

from app.extraction import extract_text
from app.sectioning import split_into_sections

DOCX_DIR = REPO_ROOT / "test-documents" / "docx"
PDF_DIR = REPO_ROOT / "test-documents" / "pdf"

BODY_FONTSIZE = 11
HEADING_FONTSIZE = 16
LINE_GAP = 30
PAGE_MARGIN = 72
PAGE_WIDTH = 595.0  # PyMuPDF's default fitz.open().new_page() size (A4)
USABLE_TEXT_WIDTH = PAGE_WIDTH - PAGE_MARGIN
# 450 (not a full page's worth, e.g. 720) is deliberate: it caps a page at 13
# lines, so the larger scenarios (C1, SOP: 19-21 lines each) genuinely span
# 2 PDF pages, exercising write_pdf's page-break branch and real multi-page
# TOC/page-number tagging -- while the smaller scenarios (A, B: 12 lines
# each) still fit on one page. A full-page value never exercised the break
# at all, since no scenario in this plan reaches ~22 lines.
PAGE_USABLE_BOTTOM = 450

STRUCTURAL = "structural"
ALL_CAPS = "all_caps"
MIXED = "mixed"
FONT_SIZE = "font_size"
NONE_CONVENTION = "none"


def write_docx(path, sections, convention):
    doc = Document()
    for i, sec in enumerate(sections):
        heading = sec["heading"]
        if heading is not None:
            if convention == STRUCTURAL:
                doc.add_paragraph(heading, style="Heading 1")
            elif convention == ALL_CAPS:
                doc.add_paragraph(heading)
            elif convention == FONT_SIZE:
                p = doc.add_paragraph()
                run = p.add_run(heading)
                run.font.size = Pt(HEADING_FONTSIZE)
            elif convention == MIXED:
                if i % 2 == 0:
                    doc.add_paragraph(heading, style="Heading 1")
                else:
                    doc.add_paragraph(heading)
            elif convention == NONE_CONVENTION:
                doc.add_paragraph(heading)
            else:
                raise ValueError(f"unknown convention: {convention}")
        for body_text in sec["body"]:
            doc.add_paragraph(body_text)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))


def _wrap_line(text, fontsize, max_width):
    """Split text into lines that each fit max_width at fontsize.

    page.insert_text() does not wrap -- a line wider than the page silently
    clips (both visually and in extraction) at the page edge, with the
    clipped-off text simply gone. Wrapping here and joining with "\\n" in one
    insert_text call keeps the paragraph as a single dict-mode block (same
    technique the existing extraction tests already rely on for wrapped
    paragraphs), so this only affects rendering, not paragraph granularity.
    """
    words = text.split(" ")
    lines = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if fitz.get_text_length(candidate, fontsize=fontsize) <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def write_pdf(path, sections, convention):
    pdf = fitz.open()
    page = pdf.new_page()
    state = {"page": page, "y": PAGE_MARGIN, "page_number": 1}
    toc_entries = []

    def emit(text, fontsize):
        lines = _wrap_line(text, fontsize, USABLE_TEXT_WIDTH)
        if state["y"] > PAGE_USABLE_BOTTOM:
            state["page"] = pdf.new_page()
            state["y"] = PAGE_MARGIN
            state["page_number"] += 1
        state["page"].insert_text((PAGE_MARGIN, state["y"]), "\n".join(lines), fontsize=fontsize)
        state["y"] += LINE_GAP * len(lines)
        return state["page_number"]

    for i, sec in enumerate(sections):
        heading = sec["heading"]
        if heading is not None:
            fontsize = HEADING_FONTSIZE if convention == FONT_SIZE else BODY_FONTSIZE
            heading_page = emit(heading, fontsize)
            if convention == STRUCTURAL:
                toc_entries.append([1, heading, heading_page])
            elif convention == MIXED and i % 2 == 0:
                toc_entries.append([1, heading, heading_page])
        for body_text in sec["body"]:
            emit(body_text, BODY_FONTSIZE)

    if toc_entries:
        pdf.set_toc(toc_entries)
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf.save(str(path))
    pdf.close()


def expected_heading_sequence(sections):
    return [sec["heading"] for sec in sections if sec["heading"] is not None]


def validate(path, file_type, sections):
    paragraphs = extract_text(str(path), file_type)
    result_sections = split_into_sections(paragraphs)
    got = [s.heading for s in result_sections]
    expected = expected_heading_sequence(sections)

    if not expected:
        assert all(h.startswith("Paragraph ") for h in got), (
            f"{path.name}: expected no real headings (fallback sections only), got {got}"
        )
        print(f"OK   {path.name}: {len(got)} paragraph-fallback sections, no false headings")
        return

    assert got == expected, f"{path.name}: expected headings {expected}, got {got}"
    print(f"OK   {path.name}: {len(got)} sections, headings match exactly")


def generate_and_validate(name, version, sections, convention):
    docx_path = DOCX_DIR / f"{name}_{version}.docx"
    pdf_path = PDF_DIR / f"{name}_{version}.pdf"
    write_docx(docx_path, sections, convention)
    write_pdf(pdf_path, sections, convention)
    validate(docx_path, "docx", sections)
    validate(pdf_path, "pdf", sections)


# --- Scenario A: numeric-only value changes, no structural change.
# Heading convention: structural (DOCX "Heading 1" style / PDF embedded TOC).

SCENARIO_A_V1 = [
    {"heading": "Effective Date", "body": ["This procedure is effective from 2024-01-15."]},
    {"heading": "Storage Temperature", "body": ["Store the reference standard at -20°C."]},
    {"heading": "Batch Size", "body": ["Manufacture in batches of 1,000 mg per lot."]},
    {"heading": "Reference Standard Weighing", "body": ["Weigh 50 mg of Batch 12 reference standard for the assay."]},
    {"heading": "Container Specification", "body": ["Dispense the solution into a 10 mL amber glass vial."]},
    {"heading": "Calibration Frequency", "body": ["Calibrate the analytical balance every 30 days using a 200 g reference weight."]},
]

SCENARIO_A_V2 = [
    {"heading": "Effective Date", "body": ["This procedure is effective from 2024-03-20."]},
    {"heading": "Storage Temperature", "body": ["Store the reference standard at -70°C."]},
    {"heading": "Batch Size", "body": ["Manufacture in batches of 2,000 mg per lot."]},
    {"heading": "Reference Standard Weighing", "body": ["Weigh 55 mg of Batch 13 reference standard for the assay."]},
    {"heading": "Container Specification", "body": ["Dispense the solution into a 10 L amber glass vial."]},
    {"heading": "Calibration Frequency", "body": ["Calibrate the analytical balance every 30 days using a 200 g reference weight."]},
]

# --- Scenario B: wording/reason changes, no structural change.
# Heading convention: ALL-CAPS (no numbering prefix, no Word style, no TOC).

SCENARIO_B_V1 = [
    {"heading": "RECORD RETENTION", "body": ["The quality control department shall retain all batch records for five years."]},
    {"heading": "SAMPLE HANDLING", "body": ["Samples must be thoroughly mixed prior to analysis."]},
    {"heading": "APPROVAL RESPONSIBILITY", "body": ["The Production Supervisor shall verify equipment cleanliness before use."]},
    {"heading": "REFERENCE DOCUMENT", "body": ["Follow the cleaning procedure described in the Master Cleaning SOP."]},
    {"heading": "PROCESS SEQUENCE", "body": ["Calibrate the instrument, then perform the system suitability test, and finally begin sample analysis."]},
    {"heading": "RESULT REPORTING", "body": ["Report results to two decimal places after review."]},
]

SCENARIO_B_V2 = [
    {"heading": "RECORD RETENTION", "body": ["The Quality Control department shall retain all batch records for five years."]},
    {"heading": "SAMPLE HANDLING", "body": ["Samples must be completely mixed prior to analysis."]},
    {"heading": "APPROVAL RESPONSIBILITY", "body": ["The Quality Assurance Officer shall verify equipment cleanliness before use."]},
    {"heading": "REFERENCE DOCUMENT", "body": ["Follow the cleaning procedure described in the Equipment Sanitation SOP."]},
    {"heading": "PROCESS SEQUENCE", "body": ["Perform the system suitability test, then calibrate the instrument, and finally begin sample analysis."]},
    {"heading": "RESULT REPORTING", "body": ["Report results to two decimal places after review and verification."]},
]

# --- Scenario C1: heavy renumbering, reordering, duplicate heading text,
# section deletion (v1 has "4.0 Batch Record Archival", v2 doesn't) and
# section addition. Heading convention: mixed (alternating Word-style/TOC
# and plain-numbered-text-only) -- the exact shape of the swallowing bug
# the heading-detection plan's Task 1 fixed.
#
# Note: the original C1_v1.txt/C1_v2.txt body line under "7.0 Analytical
# Results Table" reads "10.5 | 20.3 | conforms". Verified directly against
# the current (unmodified, already-shipped) backend/app/sectioning.py: this
# text matches HEADING_NUMBER_PATTERN (r"^\s*\d+(\.\d+)+\s+\S.*$") -- "10.5"
# looks exactly like a heading number -- so it gets split out as its own
# spurious one-line heading/section, identically for the original TXT file
# and for these DOCX/PDF translations (sectioning.py runs unchanged
# regardless of source format). This is a pre-existing latent false-positive
# shape in already-reviewed, already-shipped code, not something introduced
# by this plan -- fixing it is out of scope here (would require its own
# spec/plan/review cycle). The fixture text below is reworded to
# "Result: 10.5, 20.3, conforms" (does not start with digits, so it can
# never match the pattern) solely to avoid tripping this edge case in an
# otherwise-unrelated fixture-generation task. Do not "fix" this by editing
# backend/app/sectioning.py -- that file is out of scope for this entire
# plan.

SCENARIO_C1_V1 = [
    {"heading": "1.0 Scope", "body": ["This procedure applies to all analytical testing performed in the QC laboratory."]},
    {"heading": "2.0 Sample Preparation", "body": ["Dilute the sample to 100 mL with mobile phase before injection."]},
    {"heading": "3.0 Quality Review", "body": ["The Quality Assurance reviewer shall check all raw data for transcription errors."]},
    {"heading": "3.0 Quality Review", "body": ["A supervisor shall countersign the quality review checklist prior to submission."]},
    {"heading": "4.0 Batch Record Archival", "body": ["Completed batch records shall be archived in the document control room for ten years."]},
    {"heading": "5.0 Equipment Qualification", "body": ["All analytical balances shall be requalified annually by the metrology team."]},
    {"heading": "6.0 Documentation Review", "body": ["A second analyst shall independently review all calculations before batch release."]},
    {"heading": "7.0 Analytical Results Table", "body": ["Results are summarized below.", "Result: 10.5, 20.3, conforms"]},
    {"heading": "8.0 Final Disposition", "body": ["The QA Manager shall issue the final batch disposition after all reviews are complete.", "The stability chamber log shall be filed with the batch record."]},
]

SCENARIO_C1_V2 = [
    {"heading": "1.0 Scope", "body": ["This procedure applies to all analytical testing performed in the QC laboratory."]},
    {"heading": "3.0 Quality Review", "body": ["The Quality Assurance reviewer shall check all raw data for transcription errors."]},
    {"heading": "3.0 Quality Review", "body": ["A supervisor shall countersign the quality review checklist prior to submission."]},
    {"heading": "6.5 Documentation Review", "body": ["A second analyst shall independently review all calculations before batch release."]},
    {"heading": "7.0 Analytical Results Table", "body": ["Results are summarized below.", "Result: 10.5, 20.3, conforms"]},
    {"heading": "2.0 Sample Preparation", "body": ["Dilute the sample to 100 mL with mobile phase before injection."]},
    {"heading": "5.0 Qualifying the Equipment", "body": ["All analytical balances shall be requalified annually by the metrology team."]},
    {"heading": "8.0 Final Disposition", "body": ["The QA Manager shall issue the final batch disposition after all reviews are complete."]},
    {"heading": "9.0 Environmental Monitoring", "body": ["Environmental monitoring of the manufacturing area shall be performed weekly using settle plates."]},
    {"heading": "10.0 Long-Term Sample Retention", "body": ["The stability chamber log shall be filed together with the batch record for long-term retention."]},
]

# --- Scenario C2: plain paragraphs, no headings at all (matches the
# original TXT content exactly). Heading convention: none.

SCENARIO_C2_V1 = [
    {"heading": None, "body": [
        "All personnel entering the cleanroom must wear appropriate gowning including gloves, mask, and coverall.",
        "Hand sanitization is required immediately before gowning and after any interruption in cleanroom work.",
        "Environmental monitoring samples are collected weekly by the quality control team.",
        "Any excursion from the established alert limits must be reported to the Quality Assurance Manager within 24 hours.",
    ]},
]

SCENARIO_C2_V2 = [
    {"heading": None, "body": [
        "All personnel entering the cleanroom must wear appropriate gowning including gloves, mask, coverall, and safety glasses.",
        "Hand sanitization is required immediately before gowning and after any interruption in cleanroom work.",
        "Environmental monitoring samples are collected weekly by the quality control team.",
        "Any excursion from the established alert limits must be reported to the Quality Assurance Manager within 12 hours.",
    ]},
]

# --- Scenario SOP: full realistic SOP, wording/numeric changes, section
# additions and a moved paragraph becoming its own new section.
# Heading convention: font-size only (Pt(16) vs 11pt body, no Word style,
# no numbering prefix).

SCENARIO_SOP_V1 = [
    {"heading": "Scope", "body": ["This procedure applies to the manufacture of Product X tablets at Site A."]},
    {"heading": "Responsibilities", "body": ["The Quality Control Manager shall review and approve all batch records prior to release."]},
    {"heading": "Materials", "body": ["The active ingredient shall be stored at 2°C to 8°C prior to use.", "Material shall not be used beyond 24 months from the date of manufacture."]},
    {"heading": "Assay Acceptance Criteria", "body": ["Assay acceptance criterion: 95.0% to 105.0%."]},
    {"heading": "Sample Preparation", "body": ["Weigh 10 mg of sample and dilute to 100 mL with mobile phase."]},
    {"heading": "Sample Analysis", "body": ["Inject 20 microliters into the HPLC system and record the chromatogram."]},
    {"heading": "Effective Date", "body": ["This procedure is effective from 01 Jan 2024."]},
    {"heading": "Reference Documents", "body": ["Refer to the Master Calculation SOP for detailed calculation methods."]},
    {"heading": "Deviation Handling", "body": ["Any deviation from this procedure shall be documented and approved by the Quality Assurance Manager prior to implementation."]},
]

SCENARIO_SOP_V2 = [
    {"heading": "Scope", "body": ["This procedure applies to the manufacture of Product X tablets at Site A."]},
    {"heading": "Responsibilities", "body": ["The Quality Assurance Manager shall review and approve all batch records prior to release."]},
    {"heading": "Materials", "body": ["The active ingredient shall be stored at 36°F to 46°F prior to use."]},
    {"heading": "Assay Acceptance Criteria", "body": ["Assay acceptance criterion: 98.0% to 102.0%."]},
    {"heading": "Sample Preparation", "body": ["Weigh 20 mg of sample and dilute to 200 mL with mobile phase."]},
    {"heading": "Sample Analysis", "body": ["Filter the sample through a membrane, then inject 20 microliters into the HPLC system and record the chromatogram."]},
    {"heading": "Effective Date", "body": ["This procedure is effective from 15 Mar 2024."]},
    {"heading": "Reference Documents", "body": ["Refer to the Analytical Validation SOP for detailed calculation methods."]},
    {"heading": "Storage and Shelf Life", "body": ["Material shall not be used beyond 24 months from the date of manufacture."]},
    {"heading": "Training Requirements", "body": ["All analysts performing this procedure shall complete method-specific training prior to independent testing."]},
]


def main():
    generate_and_validate("A", "v1", SCENARIO_A_V1, STRUCTURAL)
    generate_and_validate("A", "v2", SCENARIO_A_V2, STRUCTURAL)
    generate_and_validate("B", "v1", SCENARIO_B_V1, ALL_CAPS)
    generate_and_validate("B", "v2", SCENARIO_B_V2, ALL_CAPS)
    generate_and_validate("C1", "v1", SCENARIO_C1_V1, MIXED)
    generate_and_validate("C1", "v2", SCENARIO_C1_V2, MIXED)
    generate_and_validate("C2", "v1", SCENARIO_C2_V1, NONE_CONVENTION)
    generate_and_validate("C2", "v2", SCENARIO_C2_V2, NONE_CONVENTION)
    generate_and_validate("SOP", "v1", SCENARIO_SOP_V1, FONT_SIZE)

    # SOP v2 has an exact 10-heading-vs-10-body block-count tie, which would
    # make the PDF font-size baseline resolve to the heading size instead of
    # the body size (see this task's docstring/plan notes). One extra
    # body-only trailing paragraph, present only in the PDF fixture, breaks
    # the tie. The DOCX fixture doesn't need it (its baseline strategy is
    # Normal-style-or-11.0, not mode-based) so it stays an exact translation
    # of SOP_v2.txt.
    docx_path = DOCX_DIR / "SOP_v2.docx"
    write_docx(docx_path, SCENARIO_SOP_V2, FONT_SIZE)
    validate(docx_path, "docx", SCENARIO_SOP_V2)

    pdf_path = PDF_DIR / "SOP_v2.pdf"
    sop_v2_pdf_sections = SCENARIO_SOP_V2 + [
        {"heading": None, "body": ["This marks the end of the procedure."]}
    ]
    write_pdf(pdf_path, sop_v2_pdf_sections, FONT_SIZE)
    validate(pdf_path, "pdf", sop_v2_pdf_sections)


if __name__ == "__main__":
    main()
