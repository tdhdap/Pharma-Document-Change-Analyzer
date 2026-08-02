import fitz
from docx import Document as DocxDocument

from app.models import Paragraph
from app.sectioning import _looks_like_heading_shape

HEADING_STYLE_PREFIXES = ("Heading", "Title")

DOCX_DEFAULT_BODY_SIZE_PT = 11.0
DOCX_HEADING_SIZE_DELTA_PT = 2.0


def _docx_paragraph_font_size_pt(para) -> float | None:
    if para.runs and para.runs[0].font.size is not None:
        return para.runs[0].font.size.pt
    if para.style and para.style.font.size is not None:
        return para.style.font.size.pt
    return None


def _docx_body_baseline_pt(doc) -> float:
    normal_size = doc.styles["Normal"].font.size
    if normal_size is not None:
        return normal_size.pt
    return DOCX_DEFAULT_BODY_SIZE_PT


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

    toc_titles_by_page: dict[int, set[str]] = {}
    for _level, title, page_number in doc.get_toc():
        toc_titles_by_page.setdefault(page_number, set()).add(title.strip())

    for page_index, page in enumerate(doc):
        page_number = page_index + 1
        text = page.get_text().strip()
        if not text:
            continue
        page_toc_titles = toc_titles_by_page.get(page_number, set())
        for para in text.split("\n\n"):
            para = para.strip()
            if not para:
                continue
            # Check if this block contains a TOC heading mixed with other content
            lines = [line.strip() for line in para.split("\n") if line.strip()]
            matched_heading_lines = [line for line in lines if line in page_toc_titles]

            # Only split on single newlines if: a TOC heading exists in this block AND there's mixed content
            if matched_heading_lines and len(lines) > 1:
                # Block contains a heading plus other text — split them as separate paragraphs
                for line in lines:
                    paragraphs.append(
                        Paragraph(text=line, page=page_number, is_heading=line in page_toc_titles)
                    )
            else:
                # Block is either a single item or no TOC match — keep as single paragraph
                paragraphs.append(
                    Paragraph(text=para, page=page_number, is_heading=para in page_toc_titles)
                )
    doc.close()
    return paragraphs


def _extract_docx(file_path: str) -> list[Paragraph]:
    doc = DocxDocument(file_path)
    baseline_pt = _docx_body_baseline_pt(doc)

    paragraphs: list[Paragraph] = []
    index = 0
    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        style_name = para.style.name if para.style else ""
        is_heading_style = style_name.startswith(HEADING_STYLE_PREFIXES)

        size_pt = _docx_paragraph_font_size_pt(para)
        is_heading_size = (
            size_pt is not None
            and size_pt >= baseline_pt + DOCX_HEADING_SIZE_DELTA_PT
            and _looks_like_heading_shape(text)
        )

        paragraphs.append(
            Paragraph(
                text=text,
                paragraph_index=index,
                is_heading=is_heading_style or is_heading_size,
            )
        )
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
