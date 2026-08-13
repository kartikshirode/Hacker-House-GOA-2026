"""Metrics for retrieval quality and latency reporting."""

from __future__ import annotations

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
