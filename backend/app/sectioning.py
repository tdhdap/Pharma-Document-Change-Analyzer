import re

from app.models import Paragraph, Section

HEADING_NUMBER_PATTERN = re.compile(r"^\s*\d+(\.\d+)+\s+\S.*$")
MAX_HEADING_LENGTH = 120
MAX_HEADING_WORDS = 12


def _looks_like_heading_shape(text: str) -> bool:
    if len(text) > MAX_HEADING_LENGTH:
        return False
    if len(text.split()) > MAX_HEADING_WORDS:
        return False
    if text.rstrip().endswith((".", ",", ";")):
        return False
    return True


def _looks_like_numbered_heading(text: str) -> bool:
    return bool(HEADING_NUMBER_PATTERN.match(text)) and _looks_like_heading_shape(text)


def _looks_like_all_caps_heading(text: str) -> bool:
    return text.isupper() and _looks_like_heading_shape(text)


def _is_heading_paragraph(p: Paragraph) -> bool:
    if p.is_heading:
        return True
    if not p.allow_text_pattern_heading:
        return False
    if _looks_like_numbered_heading(p.text):
        return True
    if _looks_like_all_caps_heading(p.text):
        return True
    return False


def split_into_sections(paragraphs: list[Paragraph]) -> list[Section]:
    heading_indices = [i for i, p in enumerate(paragraphs) if _is_heading_paragraph(p)]

    if not heading_indices:
        return [
            Section(heading=f"Paragraph {i + 1}", paragraphs=[p])
            for i, p in enumerate(paragraphs)
        ]

    sections: list[Section] = []
    if heading_indices[0] > 0:
        sections.append(Section(heading="Preamble", paragraphs=paragraphs[: heading_indices[0]]))

    for idx, start in enumerate(heading_indices):
        end = heading_indices[idx + 1] if idx + 1 < len(heading_indices) else len(paragraphs)
        heading_text = paragraphs[start].text
        body = paragraphs[start + 1 : end]
        sections.append(Section(heading=heading_text, paragraphs=body))

    return sections
