from typing import Callable

import numpy as np

from app.embeddings import embed_texts, cosine_similarity_matrix
from app.matching import greedy_match
from app.models import Section, SectionMatch, SectionMatchResult


def _section_text(section: Section) -> str:
    body = " ".join(p.text for p in section.paragraphs)
    return f"{section.heading} {body}".strip()


def match_sections(
    old_sections: list[Section],
    new_sections: list[Section],
    embed_fn: Callable[[list[str]], np.ndarray] = embed_texts,
    threshold: float = 0.5,
) -> SectionMatchResult:
    if not old_sections or not new_sections:
        return SectionMatchResult(
            matches=[],
            deleted_indices=list(range(len(old_sections))),
            inserted_indices=list(range(len(new_sections))),
        )

    old_texts = [_section_text(s) for s in old_sections]
    new_texts = [_section_text(s) for s in new_sections]
    scores = cosine_similarity_matrix(embed_fn(old_texts), embed_fn(new_texts))

    pairs = greedy_match(scores, threshold)
    matches = [SectionMatch(old_index=i, new_index=j, score=score) for i, j, score in pairs]

    matched_old = {m.old_index for m in matches}
    matched_new = {m.new_index for m in matches}
    deleted = [i for i in range(len(old_sections)) if i not in matched_old]
    inserted = [j for j in range(len(new_sections)) if j not in matched_new]
    return SectionMatchResult(matches=matches, deleted_indices=deleted, inserted_indices=inserted)
