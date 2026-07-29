import numpy as np

from app.models import Section, Paragraph
from app.section_matching import match_sections


def fake_embed_fn(texts: list[str]) -> np.ndarray:
    # Hand-crafted vectors: index position encodes "topic" so cosine similarity
    # is predictable without calling a real model.
    vector_by_text = {
        "Old A body a": np.array([1.0, 0.0, 0.0]),
        "Old B body b": np.array([0.0, 1.0, 0.0]),
        "New A body a": np.array([0.9, 0.1, 0.0]),
        "New C body c": np.array([0.0, 0.0, 1.0]),
    }
    return np.array([vector_by_text[t] for t in texts])


def test_match_sections_pairs_similar_sections_and_flags_the_rest():
    old_sections = [
        Section(heading="Old A", paragraphs=[Paragraph(text="body a")]),
        Section(heading="Old B", paragraphs=[Paragraph(text="body b")]),
    ]
    new_sections = [
        Section(heading="New A", paragraphs=[Paragraph(text="body a")]),
        Section(heading="New C", paragraphs=[Paragraph(text="body c")]),
    ]

    result = match_sections(old_sections, new_sections, embed_fn=fake_embed_fn, threshold=0.5)

    assert len(result.matches) == 1
    assert result.matches[0].old_index == 0
    assert result.matches[0].new_index == 0
    assert result.deleted_indices == [1]
    assert result.inserted_indices == [1]


def test_match_sections_handles_empty_input():
    result = match_sections([], [], embed_fn=fake_embed_fn, threshold=0.5)
    assert result.matches == []
    assert result.deleted_indices == []
    assert result.inserted_indices == []
