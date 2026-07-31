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


def test_default_threshold_excludes_a_058_similarity_match():
    old_sections = [
        Section(heading="Deleted Section", paragraphs=[Paragraph(text="unrelated old content")]),
    ]
    new_sections = [
        Section(heading="Added Section", paragraphs=[Paragraph(text="unrelated new content")]),
    ]

    def fake_058_embed_fn(texts: list[str]) -> np.ndarray:
        # Two vectors with cosine similarity of exactly 0.588 - mirrors the
        # real false-match score found when testing C1_v1.txt/C1_v2.txt.
        # Keyed by exact _section_text output (heading + " " + body), since
        # match_sections calls embed_fn separately for old and new texts
        # and each call must return one row per input string.
        vector_by_text = {
            "Deleted Section unrelated old content": np.array([1.0, 0.0]),
            "Added Section unrelated new content": np.array([0.588, (1 - 0.588 ** 2) ** 0.5]),
        }
        return np.array([vector_by_text[t] for t in texts])

    result = match_sections(old_sections, new_sections, embed_fn=fake_058_embed_fn)

    assert result.matches == []
    assert result.deleted_indices == [0]
    assert result.inserted_indices == [0]
