from app.embeddings import embed_texts, cosine_similarity_matrix


def test_embed_texts_returns_one_vector_per_input():
    vectors = embed_texts(["hello world", "goodbye world"])
    assert vectors.shape[0] == 2


def test_cosine_similarity_matrix_shape():
    a = embed_texts(["The cat sat on the mat."])
    b = embed_texts(["The dog sat on the mat.", "Quantum entanglement in solid-state physics."])
    scores = cosine_similarity_matrix(a, b)
    assert scores.shape == (1, 2)


def test_similar_sentences_score_higher_than_dissimilar_ones():
    a = embed_texts(["Samples shall be stored at 25 degrees Celsius."])
    b = embed_texts([
        "Samples must be kept at a temperature of 25 degrees Celsius.",
        "The quarterly finance report is due next Tuesday.",
    ])
    scores = cosine_similarity_matrix(a, b)
    assert scores[0][0] > scores[0][1]
