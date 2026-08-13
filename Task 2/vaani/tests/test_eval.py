from vaani.eval import mrr_at_k, percentiles, recall_at_k


def test_mrr_first_hit_position():
    assert mrr_at_k(["a", "b", "c"], {"a"}) == 1.0
    assert mrr_at_k(["a", "b", "c"], {"c"}) == 1.0 / 3
    assert mrr_at_k(["a", "b"], {"z"}) == 0.0
    assert mrr_at_k(["a", "b", "z"], {"z"}, k=2) == 0.0


def test_recall_counts_found_gold():
    assert recall_at_k(["a", "b", "c"], {"a", "c"}, k=3) == 1.0
    assert recall_at_k(["a", "b", "c"], {"a", "z"}, k=3) == 0.5
    assert recall_at_k([], set()) == 0.0


def test_percentiles_p100_is_max():
    stats = percentiles([10.0, 20.0, 30.0, 40.0, 100.0])
    assert stats["p100"] == 100.0
    assert stats["p50"] == 30.0
    assert stats["p50"] <= stats["p70"] <= stats["p90"] <= stats["p100"]


def test_percentiles_empty_is_zeroes():
    assert percentiles([]) == {"p50": 0.0, "p70": 0.0, "p90": 0.0, "p100": 0.0}
