import fitz  # PyMuPDF, used here only to build test fixtures
from docx import Document as DocxDocument
from docx.shared import Pt

from app.extraction import extract_text


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
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    doc.add_paragraph("5.2 Sample Preparation", style="Heading 1")
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


def test_extract_docx_does_not_flag_normal_body_text_as_heading(tmp_path):
    file_path = tmp_path / "doc.docx"
    doc = DocxDocument()
    doc.add_paragraph("This is a completely normal paragraph with no special formatting at all.")
    doc.save(str(file_path))

    paragraphs = extract_text(str(file_path), "docx")

    assert all(not p.is_heading for p in paragraphs)
