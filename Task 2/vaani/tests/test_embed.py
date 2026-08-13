import numpy as np
import pytest

from vaani.embed import Embedder


@pytest.fixture(scope="module")
def embedder():
    return Embedder()


def test_query_embeddings_shape_and_norm(embedder):
    vecs = embedder.encode_queries(["what is a corporation", "निगम क्या है"])
    assert vecs.shape == (2, 384)
    assert vecs.dtype == np.float32
    norms = np.linalg.norm(vecs, axis=1)
    assert np.allclose(norms, 1.0, atol=1e-3)


def test_passage_prefix_changes_embedding(embedder):
    text = "A corporation is a company recognized as a single legal entity."
    q = embedder.encode_queries([text])[0]
    p = embedder.encode_passages([text])[0]
    # e5 prefixes must be applied internally, so the two differ
    assert not np.allclose(q, p, atol=1e-4)


def test_semantic_neighbors_beat_strangers(embedder):
    q = embedder.encode_queries(["who wrote silent spring"])[0]
    p_good = embedder.encode_passages(["Rachel Carson wrote Silent Spring in 1962."])[0]
    p_bad = embedder.encode_passages(["The weather forecast for Goa is sunny."])[0]
    assert float(q @ p_good) > float(q @ p_bad)
