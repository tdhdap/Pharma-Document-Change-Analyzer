import collections
import itertools

import fitz
from docx import Document as DocxDocument
from docx.table import Table as DocxTable
from docx.text.paragraph import Paragraph as DocxParagraph

from app.models import Paragraph, TableCoordinate
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


def _iter_docx_paragraphs(content_iter, allow_text_pattern_heading=True, table_id_counter=None):
    if table_id_counter is None:
        table_id_counter = itertools.count()
    for item in content_iter:
        if isinstance(item, DocxParagraph):
            yield item, allow_text_pattern_heading, False, None
        elif isinstance(item, DocxTable):
            table_id = next(table_id_counter)
            seen_cells = set()
            for row_index, row in enumerate(item.rows):
                for col_index, cell in enumerate(row.cells):
                    # python-docx's row.cells returns one proxy per grid column, so a
                    # horizontally merged cell is returned once per spanned column, and a
                    # vertically merged cell reappears in every spanned row - all of these
                    # proxies wrap the same underlying <w:tc> element. python-docx exposes
                    # no public identity check for "this proxy wraps a cell I already
                    # visited", so we dedupe on the underlying XML element itself (`_tc`).
                    # Note: we must keep the element object itself in the set (not e.g.
                    # id(cell._tc)) - lxml only guarantees a stable id() for an element
                    # while some Python reference to its proxy is still alive; for a
                    # vertical merge, row.cells re-derives the continuation cell's `_tc`
                    # via a fresh lookup (tc_above) each time, so if we didn't hold a
                    # live reference here, the earlier proxy could be garbage collected
                    # and id() would no longer match on the next row.
                    if cell._tc in seen_cells:
                        continue
                    seen_cells.add(cell._tc)
                    # Once inside any table, text-pattern heading detection (ALL-CAPS,
                    # numbered) is unreliable - table cells are full of short uppercase
                    # abbreviations (HPLC, NMT 0.5%) that look exactly like a heading by
                    # shape alone. Structural signals (Word style, font-size) still work
                    # fine inside a cell, so only the text-pattern fallback is disabled.
                    # from_table is always True here regardless of what was passed in -
                    # once inside a table, it stays True even for a table nested inside
                    # a header/footer, or a table nested inside another table's cell.
                    #
                    # The row/col index here is captured at each cell's first (non-duplicate)
                    # occurrence, which is always the top-left anchor for a merged cell -
                    # verified empirically against real horizontal and vertical merges before
                    # writing this. This is the same fact the dedup above already relies on,
                    # just also read as the cell's grid coordinate.
                    position = TableCoordinate(table_id=table_id, row=row_index, col=col_index)
                    for para, _, _, inner_position in _iter_docx_paragraphs(
                        cell.iter_inner_content(),
                        allow_text_pattern_heading=False,
                        table_id_counter=table_id_counter,
                    ):
                        # A paragraph from a table nested even deeper than this cell already
                        # carries its own (innermost) table's coordinate - preserve that
                        # instead of overwriting it with this cell's position.
                        yield para, False, True, inner_position if inner_position is not None else position


def _docx_paragraph_to_model(
    para, index: int, baseline_pt: float, allow_text_pattern_heading: bool = True, from_table: bool = False,
    table_position: TableCoordinate | None = None,
) -> Paragraph | None:
    text = para.text.strip()
    if not text:
        return None
    style_name = para.style.name if para.style else ""
    is_heading_style = style_name.startswith(HEADING_STYLE_PREFIXES)

    size_pt = _docx_paragraph_font_size_pt(para)
    is_heading_size = (
        size_pt is not None
        and size_pt >= baseline_pt + DOCX_HEADING_SIZE_DELTA_PT
        and _looks_like_heading_shape(text)
    )

    return Paragraph(
        text=text,
        paragraph_index=index,
        is_heading=is_heading_style or is_heading_size,
        allow_text_pattern_heading=allow_text_pattern_heading,
        from_table=from_table,
        table_position=table_position,
    )


def _docx_header_footer_specs(doc):
    odd_even_active = doc.settings.odd_and_even_pages_header_footer
    header_specs = []
    footer_specs = []
    for section_index, section in enumerate(doc.sections):
        variants = [("header", "footer", "")]
        if section.different_first_page_header_footer:
            variants.append(("first_page_header", "first_page_footer", "First Page"))
        if odd_even_active:
            variants.append(("even_page_header", "even_page_footer", "Even Page"))
        for header_attr, footer_attr, variant_label in variants:
            header_source = getattr(section, header_attr)
            if not header_source.is_linked_to_previous:
                header_specs.append(("header", section_index, variant_label, header_source))
            footer_source = getattr(section, footer_attr)
            if not footer_source.is_linked_to_previous:
                footer_specs.append(("footer", section_index, variant_label, footer_source))
    return header_specs + footer_specs


def _header_footer_heading_text(kind, section_index, variant_label, multi_section):
    base = "Page Header" if kind == "header" else "Page Footer"
    parts = []
    if multi_section:
        parts.append(f"Section {section_index + 1}")
    if variant_label:
        parts.append(variant_label)
    if not parts:
        return base
    return f"{base} ({', '.join(parts)})"


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
    table_id_counter = itertools.count()

    paragraphs: list[Paragraph] = []
    index = 0
    for para, allow_text_pattern_heading, from_table, table_position in _iter_docx_paragraphs(
        doc.iter_inner_content(), table_id_counter=table_id_counter
    ):
        model = _docx_paragraph_to_model(
            para, index, baseline_pt, allow_text_pattern_heading, from_table, table_position
        )
        if model is not None:
            paragraphs.append(model)
            index += 1

    multi_section = len(doc.sections) > 1
    for kind, section_index, variant_label, source in _docx_header_footer_specs(doc):
        raw = list(_iter_docx_paragraphs(
            source.iter_inner_content(),
            allow_text_pattern_heading=False,
            table_id_counter=table_id_counter,
        ))
        # Filter out paragraphs with no real text (whitespace-only, or image/drawing-only
        # content where python-docx's Paragraph.text is empty) before checking emptiness,
        # so a header/footer with no actual content doesn't emit a bare pseudo-section.
        raw = [(p, atph, ft, tp) for p, atph, ft, tp in raw if p.text.strip()]
        if not raw:
            continue
        heading_text = _header_footer_heading_text(kind, section_index, variant_label, multi_section)
        paragraphs.append(Paragraph(text=heading_text, paragraph_index=index, is_heading=True))
        index += 1
        for para, allow_text_pattern_heading, from_table, table_position in raw:
            model = _docx_paragraph_to_model(
                para, index, baseline_pt, allow_text_pattern_heading, from_table, table_position
            )
            if model is not None:
                paragraphs.append(model)
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
