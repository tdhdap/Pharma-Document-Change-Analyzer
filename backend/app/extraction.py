import fitz
from docx import Document as DocxDocument

from app.models import Paragraph


def extract_text(file_path: str, file_type: str) -> list[Paragraph]:
    if file_type == "pdf":
        return _extract_pdf(file_path)
    if file_type == "docx":
        return _extract_docx(file_path)
    if file_type == "txt":
        return _extract_txt(file_path)
    raise ValueError(f"Unsupported file type: {file_type}")


def _extract_pdf(file_path: str) -> list[Paragraph]:
    paragraphs: list[Paragraph] = []
    doc = fitz.open(file_path)
    for page_index, page in enumerate(doc):
        text = page.get_text().strip()
        if not text:
            continue
        for chunk in text.split("\n\n"):
            chunk = chunk.strip()
            if chunk:
                paragraphs.append(Paragraph(text=chunk, page=page_index + 1))
    doc.close()
    return paragraphs


def _extract_docx(file_path: str) -> list[Paragraph]:
    doc = DocxDocument(file_path)
    paragraphs: list[Paragraph] = []
    index = 0
    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        paragraphs.append(Paragraph(text=text, paragraph_index=index))
        index += 1
    return paragraphs


def _extract_txt(file_path: str) -> list[Paragraph]:
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
    paragraphs = []
    for index, chunk in enumerate(content.split("\n\n")):
        chunk = chunk.strip()
        if chunk:
            paragraphs.append(Paragraph(text=chunk, paragraph_index=index))
    return paragraphs
