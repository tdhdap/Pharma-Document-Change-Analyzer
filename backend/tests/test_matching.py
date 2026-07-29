import numpy as np

from app.matching import greedy_match


def test_greedy_match_picks_highest_scoring_pairs_first():
    scores = np.array([
        [0.9, 0.1],
        [0.2, 0.8],
    ])
    result = greedy_match(scores, threshold=0.5)
    assert sorted(result) == sorted([(0, 0, 0.9), (1, 1, 0.8)])


def test_greedy_match_excludes_pairs_below_threshold():
    scores = np.array([[0.3, 0.2]])
    result = greedy_match(scores, threshold=0.5)
    assert result == []


def test_greedy_match_does_not_reuse_a_row_or_column():
    scores = np.array([
        [0.95, 0.90],
        [0.85, 0.10],
    ])
    result = greedy_match(scores, threshold=0.5)
    # row 0 best match is col 0 (0.95); row 1's only remaining option is col 1 (0.10, below threshold)
    assert result == [(0, 0, 0.95)]
