import collections

import fitz
from docx import Document as DocxDocument

from app.models import Paragraph
from app.sectioning import _looks_like_heading_shape

HEADING_STYLE_PREFIXES = ("Heading", "Title")

DOCX_DEFAULT_BODY_SIZE_PT = 11.0
DOCX_HEADING_SIZE_DELTA_PT = 2.0

PDF_HEADING_SIZE_DELTA_PT = 2.0


def _pdf_block_text(block: dict) -> str:
    line_texts = []
    for line in block["lines"]:
        line_texts.append("".join(span["text"] for span in line["spans"]))
    return " ".join(line_texts).strip()


def _pdf_block_size(block: dict) -> float | None:
    for line in block["lines"]:
        for span in line["spans"]:
            return span["size"]
    return None


# NOTE: DOCX and PDF deliberately use different baseline strategies below - this is not
# an inconsistency to "unify". PDF spans always report a concrete rendered size, so the
# mode (most common size) reliably identifies body text. DOCX body text usually resolves
# to a font size of None at both the run and style level (python-docx does not expose
# Word's true docDefaults), so a mode-based baseline over DOCX sizes would skew toward
# whichever heading size happens to be most common instead of the actual body size.
# DOCX therefore prefers the resolved "Normal" style size when available, and otherwise
# falls back to 11.0pt - Word's standard default, a documented assumption, not a measurement.
def _pdf_body_baseline_pt(sizes: list[float]) -> float | None:
    if not sizes:
        return None
    return collections.Counter(sizes).most_common(1)[0][0]


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
    doc = fitz.open(file_path)

    toc_titles_by_page: dict[int, set[str]] = {}
    for _level, title, page_number in doc.get_toc():
        toc_titles_by_page.setdefault(page_number, set()).add(title.strip())

    raw_blocks: list[tuple[str, int, float | None]] = []
    for page_index, page in enumerate(doc):
        page_number = page_index + 1
        page_dict = page.get_text("dict")
        for block in page_dict["blocks"]:
            if "lines" not in block:
                continue
            block_text = _pdf_block_text(block)
            if block_text:
                raw_blocks.append((block_text, page_number, _pdf_block_size(block)))
    doc.close()

    baseline_pt = _pdf_body_baseline_pt([size for _, _, size in raw_blocks if size is not None])

    paragraphs: list[Paragraph] = []
    for text, page_number, size in raw_blocks:
        page_toc_titles = toc_titles_by_page.get(page_number, set())
        is_heading_toc = text in page_toc_titles
        is_heading_size = (
            baseline_pt is not None
            and size is not None
            and size >= baseline_pt + PDF_HEADING_SIZE_DELTA_PT
            and _looks_like_heading_shape(text)
        )
        paragraphs.append(
            Paragraph(text=text, page=page_number, is_heading=is_heading_toc or is_heading_size)
        )
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
