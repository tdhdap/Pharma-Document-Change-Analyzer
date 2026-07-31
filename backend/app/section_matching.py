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
    threshold: float = 0.6,
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

    print(f"\n[section_matching] comparing {len(old_sections)} old section(s) against {len(new_sections)} new section(s) (threshold={threshold})")
    for i, old_section in enumerate(old_sections):
        for j, new_section in enumerate(new_sections):
            print(f"  [{i}] {old_section.heading!r}  <->  [{j}] {new_section.heading!r}   score={scores[i][j]:.3f}")

    pairs = greedy_match(scores, threshold)
    matches = [SectionMatch(old_index=i, new_index=j, score=score) for i, j, score in pairs]

    matched_old = {m.old_index for m in matches}
    matched_new = {m.new_index for m in matches}
    deleted = [i for i in range(len(old_sections)) if i not in matched_old]
    inserted = [j for j in range(len(new_sections)) if j not in matched_new]

    print("[section_matching] result:")
    for m in matches:
        print(f"  MATCHED   [{m.old_index}] {old_sections[m.old_index].heading!r}  ->  [{m.new_index}] {new_sections[m.new_index].heading!r}   score={m.score:.3f}")
    for i in deleted:
        print(f"  DELETED   [{i}] {old_sections[i].heading!r}  (no new section scored above {threshold})")
    for j in inserted:
        print(f"  INSERTED  [{j}] {new_sections[j].heading!r}  (no old section scored above {threshold})")
    print()

    return SectionMatchResult(matches=matches, deleted_indices=deleted, inserted_indices=inserted)
