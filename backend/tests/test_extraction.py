import fitz  # PyMuPDF, used here only to build test fixtures
from docx import Document as DocxDocument
from docx.shared import Inches, Pt

from app.extraction import extract_text
from app.sectioning import split_into_sections


def test_extract_txt_splits_on_blank_lines(tmp_path):
    file_path = tmp_path / "doc.txt"
    file_path.write_text("First paragraph.\n\nSecond paragraph.\n\nThird paragraph.")

    paragraphs = extract_text(str(file_path), "txt")

    assert [p.text for p in paragraphs] == [
        "First paragraph.", "Second paragraph.", "Third paragraph.",
    ]
    assert paragraphs[0].paragraph_index == 0
    assert paragraphs[2].paragraph_index == 2
    assert all(p.page is None for p in paragraphs)
    assert all(p.is_heading is False for p in paragraphs)


def test_extract_docx_reads_paragraphs(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    doc.add_paragraph("Heading One")
    doc.add_paragraph("")  # blank paragraphs should be skipped
    doc.add_paragraph("Body text.")
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")

    assert [p.text for p in paragraphs] == ["Heading One", "Body text."]
    assert paragraphs[0].paragraph_index == 0
    assert paragraphs[1].paragraph_index == 1


def test_extract_docx_tags_heading_style_paragraphs(tmp_path):
    """Isolates the structural "Heading 1" style signal: the run's font size is pinned
    to the body baseline (11pt) so the font-size signal cannot also fire here, ensuring
    this test actually discriminates the HEADING_STYLE_PREFIXES check from the size check."""
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    para = doc.add_paragraph(style="Heading 1")
    run = para.add_run("5.2 Sample Preparation")
    run.font.size = Pt(11)
    doc.add_paragraph("Weigh 10 mg of sample and dilute to volume.")
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")

    assert paragraphs[0].text == "5.2 Sample Preparation"
    assert paragraphs[0].is_heading is True
    assert paragraphs[1].is_heading is False


def test_extract_pdf_tags_page_numbers(tmp_path):
    file_path = tmp_path / "doc.pdf"
    pdf = fitz.open()
    page1 = pdf.new_page()
    page1.insert_text((72, 72), "Page one text.")
    page2 = pdf.new_page()
    page2.insert_text((72, 72), "Page two text.")
    pdf.save(str(file_path))
    pdf.close()

    paragraphs = extract_text(str(file_path), "pdf")

    assert any(p.page == 1 and "Page one text." in p.text for p in paragraphs)
    assert any(p.page == 2 and "Page two text." in p.text for p in paragraphs)
    assert all(p.is_heading is False for p in paragraphs)


def test_extract_pdf_tags_toc_entries_as_headings(tmp_path):
    file_path = tmp_path / "doc.pdf"
    pdf = fitz.open()
    page1 = pdf.new_page()
    page1.insert_text((72, 72), "5.2 Sample Preparation")
    page1.insert_text((72, 100), "10 mg of sample was weighed and diluted.")
    pdf.set_toc([[1, "5.2 Sample Preparation", 1]])
    pdf.save(str(file_path))
    pdf.close()

    paragraphs = extract_text(str(file_path), "pdf")

    heading_paragraphs = [p for p in paragraphs if p.is_heading]
    assert len(heading_paragraphs) == 1
    assert heading_paragraphs[0].text == "5.2 Sample Preparation"


def test_extract_pdf_preserves_wrapped_paragraphs_without_toc(tmp_path):
    """Regression test: wrapped paragraphs (with internal newlines) should remain as single Paragraphs
    when they don't match a TOC entry. This prevents spurious line-level diffs when paragraphs
    re-flow differently between document versions (margin/font changes)."""
    file_path = tmp_path / "doc.pdf"
    pdf = fitz.open()
    page1 = pdf.new_page()
    # Insert a multi-line block with no TOC entry: should be kept as one paragraph
    page1.insert_text((72, 72), "This is a long paragraph that\nwraps across multiple lines\nwithout any TOC entry.")
    pdf.save(str(file_path))
    pdf.close()

    paragraphs = extract_text(str(file_path), "pdf")

    # Should be exactly one paragraph (not fragmented into 3 lines)
    assert len(paragraphs) == 1
    assert paragraphs[0].page == 1
    assert paragraphs[0].is_heading is False
    assert "wraps across multiple lines" in paragraphs[0].text


def test_extract_pdf_tags_font_size_only_heading(tmp_path):
    file_path = tmp_path / "doc.pdf"
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "1.0 Scope", fontsize=11)
    page.insert_text((72, 100), "This procedure applies to all testing in the QC lab.", fontsize=11)
    page.insert_text((72, 140), "Sample Preparation", fontsize=18)
    page.insert_text((72, 165), "Weigh 10 mg of sample and dilute to volume with mobile phase.", fontsize=11)
    pdf.save(str(file_path))
    pdf.close()

    paragraphs = extract_text(str(file_path), "pdf")

    # "1.0 Scope" is deliberately the same 11pt size as the body text around it (a
    # heading-shaped distractor at body size); only "Sample Preparation" at 18pt
    # clears the baseline+2.0pt threshold and should be flagged.
    heading_texts = {p.text for p in paragraphs if p.is_heading}
    assert heading_texts == {"Sample Preparation"}


def test_extract_pdf_does_not_flag_normal_body_text_as_heading(tmp_path):
    file_path = tmp_path / "doc.pdf"
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "This is a completely normal sentence with no special formatting.", fontsize=11)
    pdf.save(str(file_path))
    pdf.close()

    paragraphs = extract_text(str(file_path), "pdf")

    assert all(not p.is_heading for p in paragraphs)


def test_extract_pdf_does_not_flag_size_below_threshold_as_heading(tmp_path):
    """A short, heading-shaped line whose size is only +1.0pt above the body baseline
    (below the +2.0pt threshold) must not be flagged as a heading."""
    file_path = tmp_path / "doc.pdf"
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "Weigh 10 mg of sample and dilute to volume with mobile phase.", fontsize=11)
    page.insert_text((72, 100), "Sample Preparation", fontsize=12)
    page.insert_text((72, 130), "Inject into the HPLC system for analysis.", fontsize=11)
    pdf.save(str(file_path))
    pdf.close()

    paragraphs = extract_text(str(file_path), "pdf")

    assert all(not p.is_heading for p in paragraphs)


def test_extract_pdf_does_not_flag_large_font_long_text_as_heading(tmp_path):
    """A large-font block whose text fails the heading shape guard (a long sentence
    ending in a period) must not be flagged as a heading, even though its size clears
    the threshold."""
    file_path = tmp_path / "doc.pdf"
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "Weigh 10 mg of sample and dilute to volume with mobile phase.", fontsize=11)
    page.insert_text(
        (72, 110),
        "This is a long sentence with a large font size but it ends with a period.",
        fontsize=18,
    )
    page.insert_text((72, 150), "Inject into the HPLC system for analysis.", fontsize=11)
    pdf.save(str(file_path))
    pdf.close()

    paragraphs = extract_text(str(file_path), "pdf")

    assert all(not p.is_heading for p in paragraphs)


def test_extract_text_rejects_unknown_type(tmp_path):
    file_path = tmp_path / "doc.xyz"
    file_path.write_text("content")

    try:
        extract_text(str(file_path), "xyz")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_extract_docx_tags_font_size_only_heading(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    doc.add_paragraph("Weigh 10 mg of sample and dilute to volume.")
    p = doc.add_paragraph()
    run = p.add_run("Sample Preparation")
    run.bold = True
    run.font.size = Pt(16)
    doc.add_paragraph("Inject into the HPLC system.")
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")

    heading_paragraphs = [p for p in paragraphs if p.is_heading]
    assert len(heading_paragraphs) == 1
    assert heading_paragraphs[0].text == "Sample Preparation"


def test_extract_docx_does_not_flag_size_below_threshold_as_heading(tmp_path):
    """Test that a paragraph with explicit font size just below the heading threshold
    (11.0pt baseline + 2.0pt delta = 13.0pt) is NOT flagged as heading, even if text looks
    like a heading."""
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    p = doc.add_paragraph()
    run = p.add_run("Sample Preparation")
    run.font.size = Pt(12)  # Only +1.0pt above baseline, below the +2.0pt threshold
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")

    assert len(paragraphs) == 1
    assert paragraphs[0].text == "Sample Preparation"
    assert paragraphs[0].is_heading is False  # Should NOT be flagged (size 12 < threshold 13)


def test_extract_docx_uses_resolved_normal_style_size_as_baseline(tmp_path):
    """When the document's "Normal" style resolves a concrete font size, the baseline
    must be that resolved size (not the hardcoded 11.0pt fallback). Here Normal is set
    to 14pt, so +1pt (15pt) is below the +2.0pt threshold and must NOT be flagged, while
    +2pt (16pt) is at the threshold and MUST be flagged."""
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    doc.styles["Normal"].font.size = Pt(14)

    p_below = doc.add_paragraph()
    p_below.add_run("Sample Preparation").font.size = Pt(15)

    p_at = doc.add_paragraph()
    p_at.add_run("Sample Analysis").font.size = Pt(16)

    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")

    by_text = {p.text: p.is_heading for p in paragraphs}
    assert by_text["Sample Preparation"] is False
    assert by_text["Sample Analysis"] is True


def test_extract_docx_does_not_flag_large_font_long_text_as_heading(tmp_path):
    """Test that a paragraph with large font size (above threshold) but whose text
    fails the shape guard (long sentence with period) is NOT flagged as heading."""
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    p = doc.add_paragraph()
    run = p.add_run("This is a long sentence with large font size but it ends with a period.")
    run.font.size = Pt(16)  # Clearly above threshold (11.0 + 2.0 = 13.0)
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")

    assert len(paragraphs) == 1
    assert paragraphs[0].is_heading is False  # Should NOT be flagged (shape guard fails due to period)


def test_extract_docx_extracts_table_cell_content(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    doc.add_paragraph("5.0 Acceptance Criteria", style="Heading 1")
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Parameter"
    table.cell(0, 1).text = "Limit"
    table.cell(1, 0).text = "Assay"
    table.cell(1, 1).text = "95.0% to 105.0%"
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")
    texts = [p.text for p in paragraphs]

    assert "Parameter" in texts
    assert "Limit" in texts
    assert "Assay" in texts
    assert "95.0% to 105.0%" in texts


def test_extract_docx_extracts_nested_table_cell_content(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    table = doc.add_table(rows=1, cols=1)
    nested = table.cell(0, 0).add_table(rows=1, cols=1)
    nested.cell(0, 0).text = "Nested cell text"
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")
    texts = [p.text for p in paragraphs]

    assert "Nested cell text" in texts


def test_extract_docx_detects_word_style_heading_inside_table_cell(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    table = doc.add_table(rows=1, cols=1)
    cell = table.cell(0, 0)
    cell.paragraphs[0].text = "5.2 Sample Preparation"
    cell.paragraphs[0].style = doc.styles["Heading 1"]
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")
    heading_paragraphs = [p for p in paragraphs if p.is_heading]

    assert len(heading_paragraphs) == 1
    assert heading_paragraphs[0].text == "5.2 Sample Preparation"


def test_extract_docx_detects_font_size_heading_inside_table_cell(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    doc.add_paragraph("Weigh 10 mg of sample and dilute to volume.")
    table = doc.add_table(rows=1, cols=1)
    p = table.cell(0, 0).paragraphs[0]
    run = p.add_run("Sample Preparation")
    run.bold = True
    run.font.size = Pt(16)
    doc.add_paragraph("Inject into the HPLC system.")
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")
    heading_paragraphs = [p for p in paragraphs if p.is_heading]

    assert len(heading_paragraphs) == 1
    assert heading_paragraphs[0].text == "Sample Preparation"


def test_extract_docx_without_tables_headers_or_footers_is_unchanged(tmp_path):
    """Regression guard: this refactor must not change extraction for documents
    that don't use any of the new features."""
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    doc.add_paragraph("1.0 Scope", style="Heading 1")
    doc.add_paragraph("This procedure applies to all testing.")
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")

    assert len(paragraphs) == 2
    assert paragraphs[0].text == "1.0 Scope"
    assert paragraphs[0].is_heading is True
    assert paragraphs[1].text == "This procedure applies to all testing."
    assert paragraphs[1].is_heading is False


def test_extract_docx_adds_page_header_section_when_header_is_set(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    doc.add_paragraph("Body content here.")
    doc.sections[0].header.paragraphs[0].text = "Confidential SOP-1234"
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")
    texts = [p.text for p in paragraphs]

    assert "Page Header" in texts
    header_index = texts.index("Page Header")
    assert paragraphs[header_index].is_heading is True
    assert "Confidential SOP-1234" in texts
    assert "Page Footer" not in texts


def test_extract_docx_adds_page_footer_section_when_footer_is_set(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    doc.add_paragraph("Body content here.")
    doc.sections[0].footer.paragraphs[0].text = "Page footer text"
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")
    texts = [p.text for p in paragraphs]

    assert "Page Footer" in texts
    footer_index = texts.index("Page Footer")
    assert paragraphs[footer_index].is_heading is True
    assert "Page footer text" in texts
    assert "Page Header" not in texts


def test_extract_docx_omits_page_header_and_footer_when_neither_is_set(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    doc.add_paragraph("Body content here.")
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")
    texts = [p.text for p in paragraphs]

    assert "Page Header" not in texts
    assert "Page Footer" not in texts


def test_extract_docx_page_header_and_footer_both_present_appear_in_order(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    doc.add_paragraph("Body content here.")
    doc.sections[0].header.paragraphs[0].text = "Header text"
    doc.sections[0].footer.paragraphs[0].text = "Footer text"
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")
    texts = [p.text for p in paragraphs]

    assert texts.index("Page Header") < texts.index("Header text")
    assert texts.index("Header text") < texts.index("Page Footer")
    assert texts.index("Page Footer") < texts.index("Footer text")


def test_extract_docx_horizontally_merged_cell_extracted_once(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).merge(table.cell(0, 1))
    table.cell(0, 0).text = "MERGED HEADER CELL"
    table.cell(1, 0).text = "A"
    table.cell(1, 1).text = "B"
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")
    texts = [p.text for p in paragraphs]

    assert texts.count("MERGED HEADER CELL") == 1
    assert texts.count("A") == 1
    assert texts.count("B") == 1


def test_extract_docx_vertically_merged_cell_extracted_once(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).merge(table.cell(1, 0))
    table.cell(0, 0).text = "VMERGED"
    table.cell(0, 1).text = "TOP RIGHT"
    table.cell(1, 1).text = "BOTTOM RIGHT"
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")
    texts = [p.text for p in paragraphs]

    assert texts.count("VMERGED") == 1
    assert texts.count("TOP RIGHT") == 1
    assert texts.count("BOTTOM RIGHT") == 1


def test_extract_docx_whitespace_only_header_produces_no_page_header_section(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    doc.add_paragraph("Body content here.")
    doc.sections[0].header.paragraphs[0].text = "   "
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")
    texts = [p.text for p in paragraphs]

    assert "Page Header" not in texts


def test_extract_docx_table_inside_header_is_extracted(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    doc.add_paragraph("Body content here.")
    header = doc.sections[0].header
    header.paragraphs[0].text = "SOP-1234"
    table = header.add_table(rows=1, cols=2, width=Inches(6))
    table.cell(0, 0).text = "Header cell A"
    table.cell(0, 1).text = "Header cell B"
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")
    texts = [p.text for p in paragraphs]

    assert "Header cell A" in texts
    assert "Header cell B" in texts


def test_extract_docx_multiple_sections_with_distinct_headers_combine(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    doc.add_paragraph("First section body.")
    doc.sections[0].header.paragraphs[0].text = "First Header"
    doc.add_section()
    # A newly added section's header defaults to is_linked_to_previous=True, in which
    # case its "paragraphs" proxy the previous section's header paragraphs (so writing
    # through it would silently overwrite "First Header" instead of creating a second,
    # distinct header). Explicitly unlink it first to get a genuinely separate header.
    doc.sections[1].header.is_linked_to_previous = False
    doc.sections[1].header.paragraphs[0].text = "Second Header"
    doc.add_paragraph("Second section body.")
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")
    texts = [p.text for p in paragraphs]

    assert "First Header" in texts
    assert "Second Header" in texts


def test_extract_docx_table_only_document_with_no_body_paragraphs(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    table = doc.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Only cell A"
    table.cell(0, 1).text = "Only cell B"
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")
    texts = [p.text for p in paragraphs]

    assert "Only cell A" in texts
    assert "Only cell B" in texts


def test_extract_docx_all_caps_table_cell_stays_in_its_section(tmp_path):
    """Test that ALL-CAPS table cell text doesn't fragment into its own heading section.
    The key is that allow_text_pattern_heading=False for table cells, so the sectioning
    logic won't detect "HPLC" as a heading."""
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    doc.add_paragraph("2.0 Acceptance Criteria", style="Heading 1")
    table = doc.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Method"
    table.cell(0, 1).text = "HPLC"
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")
    sections = split_into_sections(paragraphs)

    # Should have exactly 1 section (the main one under "2.0 Acceptance Criteria")
    # "HPLC" should NOT become its own section heading
    assert len(sections) == 1
    assert sections[0].heading == "2.0 Acceptance Criteria"
    body_texts = [p.text for p in sections[0].paragraphs]
    assert "HPLC" in body_texts


def test_extract_docx_all_caps_header_text_stays_in_page_header_section(tmp_path):
    """Test that ALL-CAPS header text doesn't fragment into its own heading.
    The key is that allow_text_pattern_heading=False for header paragraphs."""
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    doc.add_paragraph("Body content here.")
    doc.sections[0].header.paragraphs[0].text = "CONFIDENTIAL"
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")
    sections = split_into_sections(paragraphs)

    # Should have 2 sections: Preamble (body) and Page Header
    # "CONFIDENTIAL" should NOT become its own section heading under Page Header
    assert len(sections) == 2
    assert sections[0].heading == "Preamble"
    assert sections[1].heading == "Page Header"
    header_body = [p.text for p in sections[1].paragraphs]
    assert "CONFIDENTIAL" in header_body


def test_extract_docx_font_size_heading_inside_table_cell_still_detected(tmp_path):
    """Regression guard: structural signals (font-size) must still work
    inside table cells even though the text-pattern fallback is now
    disallowed there."""
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    doc.add_paragraph("Weigh 10 mg of sample and dilute to volume.")
    table = doc.add_table(rows=1, cols=1)
    p = table.cell(0, 0).paragraphs[0]
    run = p.add_run("Sample Preparation")
    run.bold = True
    run.font.size = Pt(16)
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")
    sections = split_into_sections(paragraphs)

    # Font-size should still work inside table cells, so "Sample Preparation"
    # should be detected as a heading and create its own section
    assert len(sections) == 2
    assert sections[0].heading == "Preamble"
    assert sections[1].heading == "Sample Preparation"


def test_extract_docx_all_caps_body_paragraph_still_a_heading(tmp_path):
    """Regression guard: body-paragraph ALL-CAPS detection (not from a
    table or header/footer) is completely unaffected by this change."""
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    doc.add_paragraph("SCOPE")
    doc.add_paragraph("This procedure applies to all lab testing.")
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")
    sections = split_into_sections(paragraphs)

    # Body paragraphs should still have allow_text_pattern_heading=True,
    # so "SCOPE" should be detected as a heading
    assert len(sections) == 1
    assert sections[0].heading == "SCOPE"
    body_texts = [p.text for p in sections[0].paragraphs]
    assert "This procedure applies to all lab testing." in body_texts


def test_extract_docx_table_cell_has_from_table_true(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    doc.add_paragraph("2.0 Acceptance Criteria", style="Heading 1")
    table = doc.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Method"
    table.cell(0, 1).text = "HPLC"
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")
    by_text = {p.text: p for p in paragraphs}

    assert by_text["2.0 Acceptance Criteria"].from_table is False
    assert by_text["Method"].from_table is True
    assert by_text["HPLC"].from_table is True


def test_extract_docx_body_paragraph_has_from_table_false(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    doc.add_paragraph("1.0 Scope", style="Heading 1")
    doc.add_paragraph("This procedure applies to all lab testing.")
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")

    assert all(p.from_table is False for p in paragraphs)


def test_extract_docx_header_paragraph_not_from_table(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    doc.add_paragraph("Body content here.")
    doc.sections[0].header.paragraphs[0].text = "Confidential"
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")
    header_para = next(p for p in paragraphs if p.text == "Confidential")

    assert header_para.from_table is False


def test_extract_docx_table_inside_header_has_from_table_true(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    doc.add_paragraph("Body content here.")
    header = doc.sections[0].header
    header.paragraphs[0].text = "SOP-1234"
    table = header.add_table(rows=1, cols=1, width=Inches(6))
    table.cell(0, 0).text = "Header Table Cell"
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")
    cell_para = next(p for p in paragraphs if p.text == "Header Table Cell")

    assert cell_para.from_table is True
