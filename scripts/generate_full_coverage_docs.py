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
import zipfile

from docx.oxml.ns import qn
from lxml import etree

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

# --- Table coverage --------------------------------------------------------
#
# Each table lives in exactly one section and changes in exactly one
# structural way between v1 and v2 (or, for T8, no structural way at all --
# only a cell-text edit). Combining two axes of change in one table (e.g. a
# column change alongside a merge) would reshuffle row matching and test the
# interaction between detectors instead of each detector in isolation, so
# every table here is single-purpose.
#
# T1  3.0/4.0 Equipment           - table_row_added
# T2  4.0/5.0 Sampling            - table_row_deleted
# T3  6.0/7.0 Acceptance Criteria - table_row_moved (two rows swapped)
# T4  7.0/8.0 Deviations          - table_column_added
# T5  8.0/9.0 Training            - table_column_deleted
# T6  9.0/11.0 Records            - table_column_moved (two columns swapped)
# T7  11.0 Approval               - table_cell_merge_changed (header cells
#                                    merged in v2 only)
# T8  12.0 References             - cell text edited only, no structural
#                                    change; this is what surfaces
#                                    added_table_content / deleted_table_content,
#                                    since those are suppressed inside a row
#                                    that was itself structurally added or
#                                    deleted.
# Definitions table (10.0, v1 only) - a 3x3 table inside the wholly deleted
#                                      section, so its summary reads exactly
#                                      "3 paragraphs, 1 table."
# Responsibilities table (2.0, v2 only) - the wholly added section also
#                                          carries one table.


def _add_table(doc, rows, merge=None):
    """rows is a list of row lists. merge, when given, is (row, col_start, col_end)
    and merges those cells horizontally - the shape diff_merges reports."""
    table = doc.add_table(rows=len(rows), cols=len(rows[0]))
    table.style = "Table Grid"
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            table.cell(r, c).text = value
    if merge is not None:
        r, c0, c1 = merge
        table.cell(r, c0).merge(table.cell(r, c1))
    return table


# T1 - row added
_T1_V1 = [
    ["Equipment", "Model", "Capacity"],
    ["Rotary Tablet Press", "Fette 3090", "100,000 tablets/hour"],
]
_T1_V2 = [
    ["Equipment", "Model", "Capacity"],
    ["Rotary Tablet Press", "Fette 3090", "100,000 tablets/hour"],
    ["Coating Pan", "O'Hara Labcoat 24", "25 kg batch"],
]

# T2 - row deleted
_T2_V1 = [
    ["Sampling Point", "Quantity", "Frequency"],
    ["Start of run", "10 tablets", "Once per batch"],
    ["Middle of run", "10 tablets", "Once per batch"],
    ["End of run", "10 tablets", "Once per batch"],
]
_T2_V2 = [
    ["Sampling Point", "Quantity", "Frequency"],
    ["Start of run", "10 tablets", "Once per batch"],
    ["End of run", "10 tablets", "Once per batch"],
]

# T3 - two rows swapped (Dissolution and Content Uniformity)
_T3_V1 = [
    ["Parameter", "Limit", "Method"],
    ["Assay", "95.0% to 105.0% of label claim", "HPLC"],
    ["Dissolution", "Not less than 80% in 30 minutes", "USP <711>"],
    ["Content Uniformity", "AV less than or equal to 15", "USP <905>"],
]
_T3_V2 = [
    ["Parameter", "Limit", "Method"],
    ["Assay", "95.0% to 105.0% of label claim", "HPLC"],
    ["Content Uniformity", "AV less than or equal to 15", "USP <905>"],
    ["Dissolution", "Not less than 80% in 30 minutes", "USP <711>"],
]

# T4 - column added ("Reported By")
_T4_V1 = [
    ["Deviation Type", "Severity"],
    ["Equipment malfunction", "Major"],
    ["Documentation error", "Minor"],
]
_T4_V2 = [
    ["Deviation Type", "Severity", "Reported By"],
    ["Equipment malfunction", "Major", "Line Supervisor"],
    ["Documentation error", "Minor", "QA Associate"],
]

# T5 - column deleted ("Duration")
_T5_V1 = [
    ["Course", "Frequency", "Duration"],
    ["GMP Basics", "Annual", "2 hours"],
    ["Equipment Operation", "Biennial", "4 hours"],
]
_T5_V2 = [
    ["Course", "Frequency"],
    ["GMP Basics", "Annual"],
    ["Equipment Operation", "Biennial"],
]

# T6 - two columns swapped (Retention Period and Storage Location)
_T6_V1 = [
    ["Record Type", "Retention Period", "Storage Location"],
    ["Batch Record", "7 years", "Archive Room A"],
    ["Equipment Log", "5 years", "Archive Room B"],
]
_T6_V2 = [
    ["Record Type", "Storage Location", "Retention Period"],
    ["Batch Record", "Archive Room A", "7 years"],
    ["Equipment Log", "Archive Room B", "5 years"],
]

# T7 - two header cells merged in v2 only ("Approved By" / "Reviewed By").
# v2's rows carry the exact same cell text as v1 - merge() relocates the
# second cell's paragraph into the surviving cell rather than deleting text,
# so leaving both texts as-is keeps this purely a span/structure change, with
# no accompanying content edit for the section-level paragraph diff to catch.
_T7_V1 = [
    ["Approved By", "Reviewed By", "Date"],
    ["QC Manager", "Production Manager", "2024-01-15"],
]
_T7_V2 = [
    ["Approved By", "Reviewed By", "Date"],
    ["QC Manager", "Production Manager", "2024-01-15"],
]
_T7_V2_MERGE = (0, 0, 1)

# T8 - cell text edited only, no structural change. The edit must stay mild
# enough that row matching (cosine similarity >= 0.85, see table_diff.py
# LINE_MATCH_THRESHOLD) still treats old and new as the same row - otherwise
# it reads as a delete+add pair and the table stops being single-purpose.
# T8 - one cell edited in place, no structural change. The edit stays mild enough
# that row matching (cosine >= 0.85, table_diff.LINE_MATCH_THRESHOLD) still treats
# the rows as the same, so the table reports a content change and nothing else.
_T8_V1 = [
    ["Reference", "Number", "Revision"],
    ["Equipment Manual", "EQ-MAN-01", "Rev 3, dated 10 Jan 2022"],
]
_T8_V2 = [
    ["Reference", "Number", "Revision"],
    ["Equipment Manual", "EQ-MAN-01", "Rev 4, dated 15 Mar 2024"],
]

# T9 / T10 exist in exactly ONE version each, and they are the only way to produce
# added_table_content and deleted_table_content. Verified against the pipeline:
# match_tables pairs tables by content at a 0.6 threshold, so a table with no
# counterpart is left UNMATCHED, never enters table_structure_excluded, and its
# cells fall through to the per-cell orphan path.
#
# Editing or emptying a cell cannot produce these types, and both were tried:
# an in-place edit yields a paired replace opcode and reports as a content change,
# while emptying a cell shifts row_text far enough to drop the row below the 0.85
# match threshold, so the row reports as a delete+add pair and its cells are
# suppressed. Only a whole unmatched table works.
#
# Their content is deliberately unlike every other table here, so neither is paired
# with a real counterpart at the 0.6 table-matching threshold.
_T9_V2_ONLY = [
    ["Storage Condition", "Duration", "Container"],
    ["25 C / 60 percent RH", "24 months", "HDPE bottle"],
    ["30 C / 75 percent RH", "6 months", "Blister pack"],
]
_T10_V1_ONLY = [
    ["Shipping Lane", "Carrier", "Transit Time"],
    ["Site B to Warehouse 4", "Cold chain courier", "48 hours"],
    ["Warehouse 4 to Depot", "Ambient freight", "72 hours"],
]

# Definitions table - v1 only, inside the wholly deleted "10.0 Definitions" section
_DEFINITIONS_TABLE = [
    ["Term", "Definition", "Reference"],
    ["In-process control", "Testing performed during manufacture", "QA-101"],
    ["Retained sample", "Material held for future examination", "QA-102"],
]

# Responsibilities table - v2 only, inside the wholly added "2.0 Responsibilities" section
_RESPONSIBILITIES_TABLE = [
    ["Role", "Responsibility"],
    ["Production Supervisor", "Line clearance before each run"],
    ["Quality Assurance Manager", "Final batch disposition"],
]

# heading -> (rows, merge) for each version. Keyed on the exact heading text
# used in V1_SECTIONS / V2_SECTIONS respectively, since section numbers
# differ between versions (cascade renumbering).
V1_TABLES = {
    "3.0 Equipment": (_T1_V1, None),
    "4.0 Sampling": (_T2_V1, None),
    "6.0 Acceptance Criteria": (_T3_V1, None),
    # T10 has no v2 counterpart, so match_tables leaves it unmatched and its cells
    # surface as deleted_table_content. Host choice was constrained twice over:
    # putting it in "2.0 Scope" (heading rewritten) dragged that section below the
    # match threshold and LOST section_heading_changed; putting it in "1.0 Purpose"
    # alongside T9 made SequenceMatcher pair the two tables' cells positionally, so
    # neither orphaned. It needs a MATCHED host that does not also hold T9.
    "7.0 Deviations": [(_T4_V1, None), (_T10_V1_ONLY, None)],
    "8.0 Training": (_T5_V1, None),
    "9.0 Records": (_T6_V1, None),
    "11.0 Approval": (_T7_V1, None),
    "12.0 References": (_T8_V1, None),
    "10.0 Definitions": (_DEFINITIONS_TABLE, None),
}

V2_TABLES = {
    # T9 has no v1 counterpart, so match_tables leaves it unmatched and its cells
    # surface individually as added_table_content.
    "1.0 Purpose": (_T9_V2_ONLY, None),
    "4.0 Equipment": (_T1_V2, None),
    "5.0 Sampling": (_T2_V2, None),
    "7.0 Acceptance Criteria": (_T3_V2, None),
    "8.0 Deviations": (_T4_V2, None),
    "9.0 Training": (_T5_V2, None),
    "11.0 Records": (_T6_V2, None),
    "11.0 Approval": (_T7_V2, _T7_V2_MERGE),
    "12.0 References": (_T8_V2, None),
    "2.0 Responsibilities": (_RESPONSIBILITIES_TABLE, None),
}



# ---------------------------------------------------------------------------
# Text boxes and footnotes. python-docx has no API for either, so both are raw
# OOXML. These mirror the private helpers in backend/tests/test_extraction.py,
# with one deliberate difference called out below.
# ---------------------------------------------------------------------------

# The template in test_extraction.py carries <wp:extent> but NOT <wp:docPr>, and a
# <wp:inline> without <wp:docPr> is one of the two things Word refuses to open -
# it parses fine under python-docx, so nothing in the test suite notices. The
# element order here was read off a real inline drawing emitted by python-docx's
# own add_picture(): extent, docPr, cNvGraphicFramePr, graphic.
_TEXTBOX_XML = """<w:drawing xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
    xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
    xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape">
  <wp:inline distT="0" distB="0" distL="0" distR="0">
    <wp:extent cx="2743200" cy="685800"/>
    <wp:docPr id="{shape_id}" name="Text Box {shape_id}"/>
    <wp:cNvGraphicFramePr/>
    <a:graphic>
      <a:graphicData uri="http://schemas.microsoft.com/office/word/2010/wordprocessingShape">
        <wps:wsp>
          <wps:cNvSpPr txBox="1"/>
          <wps:spPr>
            <a:xfrm><a:off x="0" y="0"/><a:ext cx="2743200" cy="685800"/></a:xfrm>
            <a:prstGeom prst="rect"><a:avLst/></a:prstGeom>
            <a:solidFill><a:srgbClr val="FFFFFF"/></a:solidFill>
            <a:ln w="9525"><a:solidFill><a:srgbClr val="000000"/></a:solidFill></a:ln>
          </wps:spPr>
          <wps:txbx><w:txbxContent>{paragraphs}</w:txbxContent></wps:txbx>
          <wps:bodyPr rot="0" vert="horz" wrap="square" anchor="t"/>
        </wps:wsp>
      </a:graphicData>
    </a:graphic>
  </wp:inline>
</w:drawing>"""


def _paragraph_xml(*run_texts):
    runs = "".join(f'<w:r><w:t xml:space="preserve">{t}</w:t></w:r>' for t in run_texts)
    return f"<w:p>{runs}</w:p>"


def _find_paragraph(doc, text):
    for paragraph in doc.paragraphs:
        if paragraph.text.strip() == text:
            return paragraph
    raise LookupError(f"no paragraph matching {text!r}")


def _attach_text_box(doc, anchor_text, box_paragraphs, shape_id):
    """Attach a text box to an EXISTING paragraph rather than creating a new one.

    Anchoring reads the box's location from the body paragraph that contains it,
    so hanging it off a real paragraph gives a meaningful anchor. It also avoids
    the other thing Word rejects: a new paragraph appended to the body lands after
    <w:sectPr>, which must stay the last child of <w:body>."""
    paragraph = _find_paragraph(doc, anchor_text)
    run = paragraph._p.makeelement(qn("w:r"), {})
    paragraph._p.append(run)
    xml = _TEXTBOX_XML.format(
        shape_id=shape_id,
        paragraphs="".join(_paragraph_xml(t) for t in box_paragraphs),
    )
    run.append(etree.fromstring(xml.encode()))


def _attach_footnote(doc, anchor_text, footnote_id):
    paragraph = _find_paragraph(doc, anchor_text)
    run = paragraph._p.makeelement(qn("w:r"), {})
    ref = run.makeelement(qn("w:footnoteReference"), {qn("w:id"): str(footnote_id)})
    run.append(ref)
    paragraph._p.append(run)


def _save_with_footnotes(doc, path, footnotes):
    """Save, then splice word/footnotes.xml into the OPC package: content-type
    override, relationship, and the part itself. python-docx cannot add this part.
    The two Word-internal separator footnotes are always included."""
    doc.save(path)
    blocks = "".join(
        f'<w:footnote w:id="{fid}">' + "".join(_paragraph_xml(t) for t in texts) + "</w:footnote>"
        for fid, texts in footnotes
    )
    footnotes_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:footnotes xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:footnote w:type="separator" w:id="-1"><w:p><w:r><w:separator/></w:r></w:p></w:footnote>'
        '<w:footnote w:type="continuationSeparator" w:id="0">'
        '<w:p><w:r><w:continuationSeparator/></w:r></w:p></w:footnote>'
        f'{blocks}</w:footnotes>'
    )
    with zipfile.ZipFile(path, "r") as zin:
        names = zin.namelist()
        content_types = zin.read("[Content_Types].xml").decode("utf-8")
        rels = zin.read("word/_rels/document.xml.rels").decode("utf-8")
        other = {n: zin.read(n) for n in names
                 if n not in ("[Content_Types].xml", "word/_rels/document.xml.rels")}
    content_types = content_types.replace(
        "</Types>",
        '<Override PartName="/word/footnotes.xml" ContentType="application/vnd.'
        'openxmlformats-officedocument.wordprocessingml.footnotes+xml"/></Types>')
    rels = rels.replace(
        "</Relationships>",
        '<Relationship Id="rIdFootnotes" Type="http://schemas.openxmlformats.org/'
        'officeDocument/2006/relationships/footnotes" Target="footnotes.xml"/></Relationships>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zout:
        zout.writestr("[Content_Types].xml", content_types)
        zout.writestr("word/_rels/document.xml.rels", rels)
        for name, blob in other.items():
            zout.writestr(name, blob)
        zout.writestr("word/footnotes.xml", footnotes_xml)


def _add_sections(doc, sections, tables=None):
    tables = tables or {}
    for heading, paragraphs in sections:
        doc.add_heading(heading, level=1)
        for text in paragraphs:
            doc.add_paragraph(text)
        if heading in tables:
            # A section may host more than one table. That matters for T10, which has
            # to sit in a section that ALREADY has a table: it needs a matched host
            # section, and every other matched section without a table was taken.
            entry = tables[heading]
            for rows, merge in (entry if isinstance(entry, list) else [entry]):
                _add_table(doc, rows, merge=merge)


# Both text boxes and the footnote hang off paragraphs inside sections that MOVE or
# get renumbered, so their anchors differ between v1 and v2 - which is the point of
# anchoring. Two boxes in DIFFERENT sections, because one box would only prove a
# label exists, not that the anchor varies.
_PROCEDURE_ANCHOR = "Compression force shall be maintained at 18 kN plus or minus 2 kN."
_PROCEDURE_ANCHOR_V2 = "Compression force shall be maintained at 20 kN plus or minus 2 kN."
_TRAINING_ANCHOR = "Operators are trained before independent operation."

_CAUTION_BOX = ["CAUTION: verify press calibration before each batch."]
_TRAINING_BOX = ["Training records are held by the QA department."]
_FOOTNOTE = ("1", ["Refer to Equipment Manual EM-004, Rev 3, for calibration procedure."])


def build_v1(path):
    doc = Document()
    _add_sections(doc, V1_SECTIONS, V1_TABLES)
    _attach_text_box(doc, _PROCEDURE_ANCHOR, _CAUTION_BOX, shape_id=1)
    _attach_text_box(doc, _TRAINING_ANCHOR, _TRAINING_BOX, shape_id=2)
    _attach_footnote(doc, _PROCEDURE_ANCHOR, _FOOTNOTE[0])
    _save_with_footnotes(doc, path, [_FOOTNOTE])


def build_v2(path):
    doc = Document()
    _add_sections(doc, V2_SECTIONS, V2_TABLES)
    _attach_text_box(doc, _PROCEDURE_ANCHOR_V2, _CAUTION_BOX, shape_id=1)
    _attach_text_box(doc, _TRAINING_ANCHOR, _TRAINING_BOX, shape_id=2)
    _attach_footnote(doc, _PROCEDURE_ANCHOR_V2, _FOOTNOTE[0])
    _save_with_footnotes(doc, path, [_FOOTNOTE])


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    build_v1(os.path.join(OUT_DIR, "FullCoverageDemo_v1.docx"))
    build_v2(os.path.join(OUT_DIR, "FullCoverageDemo_v2.docx"))
    print(f"wrote FullCoverageDemo_v1.docx and _v2.docx to {OUT_DIR}")


if __name__ == "__main__":
    main()
