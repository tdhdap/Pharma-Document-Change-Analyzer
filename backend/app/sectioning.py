import re

from app.models import Paragraph, Section

HEADING_NUMBER_PATTERN = re.compile(r"^\s*\d+(\.\d+)+\s+\S.*$")
MAX_HEADING_LENGTH = 120
MAX_HEADING_WORDS = 12


def _looks_like_heading(text: str) -> bool:
    if not HEADING_NUMBER_PATTERN.match(text):
        return False
    if len(text) > MAX_HEADING_LENGTH:
        return False
    if len(text.split()) > MAX_HEADING_WORDS:
        return False
    if text.rstrip().endswith((".", ",", ";")):
        return False
    return True


def split_into_sections(paragraphs: list[Paragraph]) -> list[Section]:
    heading_indices = [i for i, p in enumerate(paragraphs) if p.is_heading]

    if not heading_indices:
        heading_indices = [i for i, p in enumerate(paragraphs) if _looks_like_heading(p.text)]

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
