import numpy as np

from vaani.retriever import Retriever, RetrievalResult


class FakeStrategy:
    def __init__(self, rows, scores):
        self.rows = np.asarray(rows, dtype=np.int64)
        self.scores = np.asarray(scores, dtype=np.float32)

    def search_rows(self, query_text, query_vec, k):
        return self.rows[:k], self.scores[:k]


class FakeStore:
    def __init__(self, n):
        self.n = n

    def lookup(self, rows):
        return [
            {"passage_id": f"md5_{r}", "eng_text": f"text {r}", "tr_text": f"पाठ {r}"}
            for r in rows
        ]


def test_rrf_fusion_order_and_attribution():
    strategies = {
        "s1": FakeStrategy([0, 1, 2], [0.9, 0.8, 0.7]),
        "s2": FakeStrategy([2, 3], [0.95, 0.5]),
    }
    r = Retriever(strategies, FakeStore(5))
    result = r.retrieve("q", np.zeros(4, dtype=np.float32), k=4)
    assert isinstance(result, RetrievalResult)
    ids = [h.passage_id for h in result.hits]
    # row 2 appears in both lists so it fuses to the top
    assert ids[0] == "md5_2"
    top = result.hits[0]
    assert sorted(top.source_strategies) == ["s1", "s2"]
    assert set(ids) == {"md5_0", "md5_1", "md5_2", "md5_3"}
    assert 0 < result.confidence <= 1.0
    assert set(result.timings_ms) >= {"s1", "s2"}


def test_empty_strategy_is_tolerated():
    strategies = {
        "s1": FakeStrategy([1], [0.9]),
        "empty": FakeStrategy([], []),
    }
    r = Retriever(strategies, FakeStore(3))
    result = r.retrieve("q", np.zeros(4, dtype=np.float32), k=3)
    assert [h.passage_id for h in result.hits] == ["md5_1"]


def test_subset_of_strategies():
    strategies = {
        "s1": FakeStrategy([0], [0.9]),
        "s2": FakeStrategy([1], [0.9]),
    }
    r = Retriever(strategies, FakeStore(3))
    result = r.retrieve("q", None, k=2, strategies=["s2"])
    assert [h.passage_id for h in result.hits] == ["md5_1"]
    assert result.hits[0].source_strategies == ["s2"]
