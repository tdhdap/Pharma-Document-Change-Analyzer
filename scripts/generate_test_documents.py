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
PAGE_USABLE_BOTTOM = 720

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


def write_pdf(path, sections, convention):
    pdf = fitz.open()
    page = pdf.new_page()
    state = {"page": page, "y": PAGE_MARGIN, "page_number": 1}
    toc_entries = []

    def emit(text, fontsize):
        if state["y"] > PAGE_USABLE_BOTTOM:
            state["page"] = pdf.new_page()
            state["y"] = PAGE_MARGIN
            state["page_number"] += 1
        state["page"].insert_text((PAGE_MARGIN, state["y"]), text, fontsize=fontsize)
        state["y"] += LINE_GAP
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
    {"heading": "1.0 Effective Date", "body": ["This procedure is effective from 2024-01-15."]},
    {"heading": "2.0 Storage Temperature", "body": ["Store the reference standard at -20°C."]},
    {"heading": "3.0 Batch Size", "body": ["Manufacture in batches of 1,000 mg per lot."]},
    {"heading": "4.0 Reference Standard Weighing", "body": ["Weigh 50 mg of Batch 12 reference standard for the assay."]},
    {"heading": "5.0 Container Specification", "body": ["Dispense the solution into a 10 mL amber glass vial."]},
    {"heading": "6.0 Calibration Frequency", "body": ["Calibrate the analytical balance every 30 days using a 200 g reference weight."]},
]

SCENARIO_A_V2 = [
    {"heading": "1.0 Effective Date", "body": ["This procedure is effective from 2024-03-20."]},
    {"heading": "2.0 Storage Temperature", "body": ["Store the reference standard at -70°C."]},
    {"heading": "3.0 Batch Size", "body": ["Manufacture in batches of 2,000 mg per lot."]},
    {"heading": "4.0 Reference Standard Weighing", "body": ["Weigh 55 mg of Batch 13 reference standard for the assay."]},
    {"heading": "5.0 Container Specification", "body": ["Dispense the solution into a 10 L amber glass vial."]},
    {"heading": "6.0 Calibration Frequency", "body": ["Calibrate the analytical balance every 30 days using a 200 g reference weight."]},
]


def main():
    generate_and_validate("A", "v1", SCENARIO_A_V1, STRUCTURAL)
    generate_and_validate("A", "v2", SCENARIO_A_V2, STRUCTURAL)


if __name__ == "__main__":
    main()
