from dataclasses import dataclass
from difflib import SequenceMatcher

from app.models import Paragraph


@dataclass
class ParagraphOpcode:
    tag: str
    old_paragraphs: list[Paragraph]
    new_paragraphs: list[Paragraph]


def diff_paragraphs(old_paragraphs: list[Paragraph], new_paragraphs: list[Paragraph]) -> list[ParagraphOpcode]:
    old_texts = [p.text for p in old_paragraphs]
    new_texts = [p.text for p in new_paragraphs]
    matcher = SequenceMatcher(None, old_texts, new_texts)

    opcodes = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        opcodes.append(
            ParagraphOpcode(
                tag=tag,
                old_paragraphs=old_paragraphs[i1:i2],
                new_paragraphs=new_paragraphs[j1:j2],
            )
        )
    return opcodes
