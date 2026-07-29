import numpy as np


def greedy_match(scores: np.ndarray, threshold: float) -> list[tuple[int, int, float]]:
    n_rows, n_cols = scores.shape
    candidates = [
        (float(scores[i][j]), i, j)
        for i in range(n_rows)
        for j in range(n_cols)
        if scores[i][j] >= threshold
    ]
    candidates.sort(key=lambda c: c[0], reverse=True)

    matched_rows: set[int] = set()
    matched_cols: set[int] = set()
    result: list[tuple[int, int, float]] = []
    for score, i, j in candidates:
        if i in matched_rows or j in matched_cols:
            continue
        result.append((i, j, score))
        matched_rows.add(i)
        matched_cols.add(j)
    return result
