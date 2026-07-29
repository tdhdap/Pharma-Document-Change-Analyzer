import numpy as np

from app.models import Paragraph
from app.move_reconciliation import reconcile_moves


def fake_embed_fn(texts: list[str]) -> np.ndarray:
    vector_by_text = {
        "The QA Manager shall sign the batch record.": np.array([1.0, 0.0]),
        "Unrelated deleted sentence.": np.array([1.0, 0.0]),
        "Unrelated inserted sentence.": np.array([0.0, 1.0]),
    }
    return np.array([vector_by_text[t] for t in texts])


def test_high_similarity_orphans_are_reclassified_as_moved():
    deletes = [(Paragraph(text="The QA Manager shall sign the batch record."), "3.0 Old Section")]
    inserts = [(Paragraph(text="The QA Manager shall sign the batch record."), "6.0 New Section")]

    moved, remaining_deletes, remaining_inserts = reconcile_moves(
        deletes, inserts, embed_fn=lambda texts: np.array([[1.0, 0.0]] * len(texts)), threshold=0.85
    )

    assert len(moved) == 1
    assert moved[0].old_section == "3.0 Old Section"
    assert moved[0].new_section == "6.0 New Section"
    assert remaining_deletes == []
    assert remaining_inserts == []


def test_low_similarity_orphans_stay_as_add_and_delete():
    deletes = [(Paragraph(text="Unrelated deleted sentence."), "2.0 Section")]
    inserts = [(Paragraph(text="Unrelated inserted sentence."), "5.0 Section")]

    moved, remaining_deletes, remaining_inserts = reconcile_moves(
        deletes, inserts, embed_fn=fake_embed_fn, threshold=0.999
    )

    assert moved == []
    assert remaining_deletes == deletes
    assert remaining_inserts == inserts


def test_empty_orphans_return_immediately():
    moved, remaining_deletes, remaining_inserts = reconcile_moves([], [], embed_fn=fake_embed_fn)
    assert moved == []
    assert remaining_deletes == []
    assert remaining_inserts == []
