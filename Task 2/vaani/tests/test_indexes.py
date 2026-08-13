import numpy as np
import pytest

from vaani.indexes import DenseIndex, LexicalIndex, map_to_parents


def unit(v):
    v = np.asarray(v, dtype=np.float32)
    return v / np.linalg.norm(v)


@pytest.fixture()
def toy_vectors():
    rng = np.random.default_rng(7)
    vecs = rng.normal(size=(50, 32)).astype(np.float32)
    vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
    # row 7 becomes a near-duplicate of the query direction
    base = unit(np.arange(32))
    vecs[7] = unit(base + rng.normal(scale=0.01, size=32).astype(np.float32))
    return vecs, base


def test_dense_index_roundtrip(tmp_path, toy_vectors):
    vecs, query = toy_vectors
    DenseIndex.build(vecs, tmp_path)
    idx = DenseIndex.load(tmp_path)
    ids, scores = idx.search(query[None, :], k=5)
    assert ids.shape == (1, 5)
    assert ids[0, 0] == 7
    assert scores[0, 0] > 0.95
    assert np.all(scores[0, :-1] >= scores[0, 1:])


def test_lexical_index_roundtrip(tmp_path):
    texts = [
        "the corporation is a legal entity recognized by law",
        "rachel carson wrote silent spring about pesticides",
        "goa beaches are popular in december",
    ]
    LexicalIndex.build(texts, tmp_path)
    idx = LexicalIndex.load(tmp_path)
    ids, scores = idx.search("who wrote silent spring", k=2)
    assert ids[0] == 1
    assert scores[0] > 0


def test_map_to_parents_dedups_keeping_best():
    child_ids = np.array([10, 11, 12, 13])
    child_scores = np.array([0.9, 0.8, 0.7, 0.6], dtype=np.float32)
    parents = {10: 3, 11: 3, 12: 5, 13: 9}
    parent_rows = np.array([parents[c] for c in child_ids])
    ids, scores = map_to_parents(child_ids, child_scores, parent_rows)
    assert list(ids) == [3, 5, 9]
    assert list(np.round(scores, 3)) == [0.9, 0.7, 0.6]
