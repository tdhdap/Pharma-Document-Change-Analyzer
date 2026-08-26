import collections
import itertools

import fitz
from docx import Document as DocxDocument
from docx.oxml import parse_xml
from docx.oxml.ns import qn
from docx.table import Table as DocxTable
from docx.text.paragraph import Paragraph as DocxParagraph

from app.models import Paragraph, TableCoordinate
from app.sectioning import _looks_like_heading_shape

_MC_FALLBACK_TAG = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback"


def _has_mc_fallback_ancestor(element) -> bool:
    # Word 2010+ wraps one user-inserted text box in a single mc:AlternateContent
    # element containing BOTH representations (mc:Choice = DrawingML, mc:Fallback =
    # VML) of the identical content - verified empirically against Word's real
    # output shape. Skipping anything under mc:Fallback keeps exactly the mc:Choice
    # copy, avoiding double extraction of the same box's content.
    ancestor = element.getparent()
    while ancestor is not None:
        if ancestor.tag == _MC_FALLBACK_TAG:
            return True
        ancestor = ancestor.getparent()
    return False


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
            # Pre-pass: a merged cell's span is the number of distinct grid rows and
            # columns its single w:tc element occupies. It cannot be read at the
            # anchor, because the positions it also occupies have not been visited
            # yet - and w:vMerge records only restart/continue, never a count.
            #
            # cell_proxies holds every proxy alive for the duration. lxml only
            # guarantees a stable identity for an element while some reference to
            # its proxy exists, and python-docx re-derives a vertically merged
            # cell's _tc on each lookup - without this, merged positions read as
            # distinct elements and every span comes back as 1.
            cell_proxies = [list(r.cells) for r in item.rows]
            rows_by_element: dict = {}
            cols_by_element: dict = {}
            for r_index, proxy_row in enumerate(cell_proxies):
                for c_index, proxy in enumerate(proxy_row):
                    rows_by_element.setdefault(proxy._tc, set()).add(r_index)
                    cols_by_element.setdefault(proxy._tc, set()).add(c_index)
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
                    position = TableCoordinate(
                        table_id=table_id, row=row_index, col=col_index,
                        row_span=len(rows_by_element.get(cell._tc, {row_index})),
                        col_span=len(cols_by_element.get(cell._tc, {col_index})),
                    )
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


def _content_iter(element, doc):
    for child in element:
        if child.tag == qn("w:p"):
            yield DocxParagraph(child, doc)
        elif child.tag == qn("w:tbl"):
            yield DocxTable(child, doc)


def _iter_text_box_paragraphs(root_element, doc):
    # python-docx has no API for text boxes at all - a paragraph containing one
    # reads as completely empty through every normal reading path (verified
    # empirically before writing this plan). Both text box formats Word uses -
    # modern DrawingML and legacy VML - wrap their actual content in a plain
    # w:txbxContent element, so this single search finds both identically with
    # no format-specific branching. The search is transitive (".//"), so it finds
    # text boxes at any nesting depth - inside table cells, inside other text
    # boxes, etc. - with no special recursion needed, unlike table extraction.
    #
    # Word 2010+ additionally wraps a single user-inserted text box in
    # mc:AlternateContent, containing both a DrawingML and a VML copy of the
    # identical content - _has_mc_fallback_ancestor skips the redundant VML
    # copy so each real text box is extracted exactly once.
    #
    # A text box's own content can itself contain a table (e.g. a callout box
    # with a small limits table) - _content_iter + _iter_docx_paragraphs
    # reuses the same table-walking logic the main body/header/footer walks
    # already use, so that content isn't silently dropped. Its from_table/
    # table_position outputs are discarded below - text-box content always
    # stays from_table=False/table_position=None regardless of origin.
    for txbx in root_element.findall(".//" + qn("w:txbxContent")):
        if _has_mc_fallback_ancestor(txbx):
            continue
        yield [para for para, _, _, _ in _iter_docx_paragraphs(_content_iter(txbx, doc))]


_FOOTNOTES_RELTYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/footnotes"
_EXCLUDED_FOOTNOTE_TYPES = {"separator", "continuationSeparator"}


def _footnotes_root(doc):
    # python-docx has no API for footnotes at all - the footnotes part loads as an
    # opaque, unparsed Part (verified empirically: it has no registered subclass for
    # the footnotes content type, so python-docx exposes only a raw .blob). The
    # relationship type is the canonical, stable way to locate it regardless of that -
    # verified empirically to be present and correctly typed even though the part
    # itself is otherwise unrecognized, and cleanly absent (no error) on documents
    # with no footnotes.
    for rel in doc.part.rels.values():
        if rel.reltype == _FOOTNOTES_RELTYPE:
            return parse_xml(rel.target_part.blob)
    return None


def _footnote_content_by_id(footnotes_root, doc):
    # Word writes two non-content footnotes used purely for print layout - a
    # "separator" and a "continuationSeparator" - identified by w:type. Real,
    # user-authored footnotes have no w:type attribute (or, per the OOXML spec's
    # allowance, an explicit w:type="normal") - both are treated as real content.
    # Keyed by w:id (a string, not necessarily contiguous or in document order) -
    # verified empirically that Word does not guarantee footnote ids are assigned
    # in reference order, so callers must join on this id, never on position.
    #
    # A footnote's content model allows both paragraphs and tables (the same content
    # model already handled for text boxes) - reusing _content_iter + _iter_docx_paragraphs
    # here means a table inside a footnote is captured correctly from the start,
    # rather than needing a second fix later the way text boxes did.
    content_by_id = {}
    for footnote in footnotes_root.findall(qn("w:footnote")):
        if footnote.get(qn("w:type")) in _EXCLUDED_FOOTNOTE_TYPES:
            continue
        footnote_id = footnote.get(qn("w:id"))
        content_by_id[footnote_id] = [
            para for para, _, _, _ in _iter_docx_paragraphs(_content_iter(footnote, doc))
        ]
    return content_by_id


def _docx_header_footer_specs(doc) -> list[tuple[str, int, str, object]]:
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


def _header_footer_heading_text(kind: str, section_index: int, variant_label: str, multi_section: bool) -> str:
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
    footnote_refs_in_order: list[str] = []
    seen_footnote_ids: set[str] = set()
    for para, allow_text_pattern_heading, from_table, table_position in _iter_docx_paragraphs(
        doc.iter_inner_content(), table_id_counter=table_id_counter
    ):
        # Collecting footnote reference ids here, in the same walk that already visits
        # every body paragraph, avoids a second full-body traversal just to find them.
        # Word 2010+ wraps a user text box in mc:AlternateContent containing both a
        # DrawingML and VML copy of identical content (the same duplication
        # _has_mc_fallback_ancestor already guards against for text-box paragraph
        # extraction) - a footnote reference inside such a box would otherwise be
        # found twice. Deduping on id additionally guards the (separate, rarer) case
        # of the same footnote genuinely being referenced more than once.
        for ref in para._p.findall(".//" + qn("w:footnoteReference")):
            if _has_mc_fallback_ancestor(ref):
                continue
            ref_id = ref.get(qn("w:id"))
            if ref_id in seen_footnote_ids:
                continue
            seen_footnote_ids.add(ref_id)
            footnote_refs_in_order.append(ref_id)
        model = _docx_paragraph_to_model(
            para, index, baseline_pt, allow_text_pattern_heading, from_table, table_position
        )
        if model is not None:
            paragraphs.append(model)
            index += 1

    multi_section = len(doc.sections) > 1
    header_footer_specs = _docx_header_footer_specs(doc)
    for kind, section_index, variant_label, source in header_footer_specs:
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

    text_box_roots = [doc.element.body] + [source._element for _, _, _, source in header_footer_specs]
    text_box_number = 0
    for root_element in text_box_roots:
        for group in _iter_text_box_paragraphs(root_element, doc):
            group = [p for p in group if p.text.strip()]
            if not group:
                continue
            text_box_number += 1
            paragraphs.append(Paragraph(text=f"Text Box {text_box_number}", paragraph_index=index, is_heading=True))
            index += 1
            for para in group:
                model = _docx_paragraph_to_model(para, index, baseline_pt, allow_text_pattern_heading=False)
                if model is not None:
                    paragraphs.append(model)
                    index += 1

    footnotes_root = _footnotes_root(doc)
    if footnotes_root is not None and footnote_refs_in_order:
        footnote_content_by_id = _footnote_content_by_id(footnotes_root, doc)
        footnote_number = 0
        for footnote_id in footnote_refs_in_order:
            group = footnote_content_by_id.get(footnote_id)
            if not group:
                continue
            group = [p for p in group if p.text.strip()]
            if not group:
                continue
            footnote_number += 1
            paragraphs.append(Paragraph(text=f"Footnote {footnote_number}", paragraph_index=index, is_heading=True))
            index += 1
            for footnote_para in group:
                model = _docx_paragraph_to_model(footnote_para, index, baseline_pt, allow_text_pattern_heading=False)
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
