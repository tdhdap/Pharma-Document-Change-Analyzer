import fitz  # PyMuPDF, used here only to build a test fixture
from docx import Document as DocxDocument

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


def test_extract_text_rejects_unknown_type(tmp_path):
    file_path = tmp_path / "doc.xyz"
    file_path.write_text("content")

    try:
        extract_text(str(file_path), "xyz")
        assert False, "expected ValueError"
    except ValueError:
        pass
