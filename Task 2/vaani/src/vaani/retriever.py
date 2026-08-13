"""Multi-strategy retrieval with reciprocal rank fusion.

A strategy is anything with search_rows(query_text, query_vec, k)
returning (row_offsets, scores) rank-ordered best first. The retriever
runs the active strategies, fuses their rankings with RRF and resolves
row offsets to passages through the store.
"""

from __future__ import annotations

import time

import numpy as np
from pydantic import BaseModel, Field

RRF_K = 60


class Hit(BaseModel):
    passage_id: str
    eng_text: str
    tr_text: str | None = None
    score: float
    source_strategies: list[str] = Field(default_factory=list)


class RetrievalResult(BaseModel):
    hits: list[Hit]
    confidence: float
    # best raw score per strategy; dense cosines are the abstention signal,
    # since RRF ranks alone cannot tell "nothing relevant exists"
    strategy_top_scores: dict[str, float] = Field(default_factory=dict)
    timings_ms: dict[str, float] = Field(default_factory=dict)


class Retriever:
    def __init__(self, strategies: dict, store):
        self.strategies = strategies
        self.store = store

    def retrieve(
        self,
        query_text: str,
        query_vec: np.ndarray | None,
        k: int = 10,
        strategies: list[str] | None = None,
    ) -> RetrievalResult:
        active = strategies or list(self.strategies)
        fused: dict[int, float] = {}
        sources: dict[int, list[str]] = {}
        timings: dict[str, float] = {}

        top_scores: dict[str, float] = {}
        for name in active:
            t0 = time.perf_counter()
            rows, scores = self.strategies[name].search_rows(query_text, query_vec, k)
            timings[name] = (time.perf_counter() - t0) * 1000
            scores = np.asarray(scores)
            top_scores[name] = float(scores[0]) if scores.size else 0.0
            for rank, row in enumerate(np.asarray(rows).tolist()):
                fused[row] = fused.get(row, 0.0) + 1.0 / (RRF_K + rank)
                sources.setdefault(row, []).append(name)

        ranked = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)[:k]
        rows = [r for r, _ in ranked]
        records = self.store.lookup(rows)

        # normalize so a row ranked first by every active strategy scores 1.0
        max_possible = len(active) / RRF_K
        hits = [
            Hit(
                passage_id=rec["passage_id"],
                eng_text=rec["eng_text"],
                tr_text=rec.get("tr_text"),
                score=score / max_possible,
                source_strategies=sources[row],
            )
            for (row, score), rec in zip(ranked, records)
        ]
        confidence = hits[0].score if hits else 0.0
        return RetrievalResult(
            hits=hits,
            confidence=confidence,
            strategy_top_scores=top_scores,
            timings_ms=timings,
        )
