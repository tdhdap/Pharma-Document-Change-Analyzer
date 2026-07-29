from typing import Callable

import numpy as np

from app.embeddings import embed_texts, cosine_similarity_matrix
from app.matching import greedy_match
from app.models import Paragraph, MovedParagraph

Orphan = tuple[Paragraph, str]


def reconcile_moves(
    orphan_deletes: list[Orphan],
    orphan_inserts: list[Orphan],
    embed_fn: Callable[[list[str]], np.ndarray] = embed_texts,
    threshold: float = 0.85,
) -> tuple[list[MovedParagraph], list[Orphan], list[Orphan]]:
    if not orphan_deletes or not orphan_inserts:
        return [], orphan_deletes, orphan_inserts

    old_texts = [p.text for p, _ in orphan_deletes]
    new_texts = [p.text for p, _ in orphan_inserts]
    scores = cosine_similarity_matrix(embed_fn(old_texts), embed_fn(new_texts))

    pairs = greedy_match(scores, threshold)

    moved = []
    matched_old, matched_new = set(), set()
    for i, j, score in pairs:
        old_p, old_section = orphan_deletes[i]
        new_p, new_section = orphan_inserts[j]
        moved.append(
            MovedParagraph(
                old_paragraph=old_p, new_paragraph=new_p,
                old_section=old_section, new_section=new_section, score=score,
            )
        )
        matched_old.add(i)
        matched_new.add(j)

    remaining_deletes = [o for i, o in enumerate(orphan_deletes) if i not in matched_old]
    remaining_inserts = [o for j, o in enumerate(orphan_inserts) if j not in matched_new]
    return moved, remaining_deletes, remaining_inserts
