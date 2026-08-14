"""Metrics for retrieval quality and latency reporting."""

from __future__ import annotations

from collections import Counter

import numpy as np


def mrr_at_k(ranked_ids: list[str], gold_ids: set[str], k: int = 10) -> float:
    for rank, pid in enumerate(ranked_ids[:k], start=1):
        if pid in gold_ids:
            return 1.0 / rank
    return 0.0


def recall_at_k(ranked_ids: list[str], gold_ids: set[str], k: int = 10) -> float:
    if not gold_ids:
        return 0.0
    found = sum(1 for pid in ranked_ids[:k] if pid in gold_ids)
    return found / len(gold_ids)


def token_f1(pred: str, ref: str) -> float:
    """Whitespace-token overlap F1, the squad-style answer score."""
    p, r = pred.split(), ref.split()
    if not p or not r:
        return 0.0
    overlap = sum((Counter(p) & Counter(r)).values())
    if not overlap:
        return 0.0
    precision, recall = overlap / len(p), overlap / len(r)
    return 2 * precision * recall / (precision + recall)


def percentiles(samples_ms: list[float]) -> dict[str, float]:
    if not samples_ms:
        return {"p50": 0.0, "p70": 0.0, "p90": 0.0, "p100": 0.0}
    arr = np.asarray(samples_ms, dtype=np.float64)
    return {
        "p50": round(float(np.percentile(arr, 50)), 2),
        "p70": round(float(np.percentile(arr, 70)), 2),
        "p90": round(float(np.percentile(arr, 90)), 2),
        "p100": round(float(arr.max()), 2),
    }
