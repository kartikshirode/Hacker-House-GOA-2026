"""Index primitives: dense HNSW (usearch), lexical BM25 (bm25s).

Both search interfaces return row offsets into the corpus passage table,
never md5 ids; the caller owns the offset-to-passage mapping. Artifacts
for one strategy live together in one directory.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np


# usearch defaults (connectivity 16, expansion_add 128, expansion_search
# 64) cost real recall on this corpus. Measured on 20K passages against
# exact float32 cosine: recall@10 0.9418 at the defaults, 0.9840 by
# raising expansion_search alone, 0.9918 with the heavier graph as well.
# The whole difference costs 0.08ms on a retrieve stage that runs in
# 1.3ms, so the defaults were buying nothing.
CONNECTIVITY = 32
EXPANSION_ADD = 256
EXPANSION_SEARCH = 256


class DenseIndex:
    FILE = "dense.usearch"

    def __init__(self, index):
        self.index = index

    @classmethod
    def build(cls, vectors: np.ndarray, out_dir: Path | str,
              connectivity: int = CONNECTIVITY,
              expansion_add: int = EXPANSION_ADD) -> "DenseIndex":
        from usearch.index import Index

        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        idx = Index(ndim=vectors.shape[1], metric="cos", dtype="f16",
                    connectivity=connectivity, expansion_add=expansion_add)
        idx.add(np.arange(len(vectors), dtype=np.int64), vectors)
        idx.save(str(out_dir / cls.FILE))
        return cls(idx)

    @classmethod
    def load(cls, dir: Path | str,
             expansion_search: int | None = None) -> "DenseIndex":
        from usearch.index import Index

        idx = Index.restore(str(Path(dir) / cls.FILE))
        # query-time only, so an index built at the old defaults still
        # gets most of the recall back without being rebuilt
        idx.expansion_search = int(
            expansion_search
            if expansion_search is not None
            else os.environ.get("VAANI_EXPANSION_SEARCH") or EXPANSION_SEARCH
        )
        return cls(idx)

    def search(self, vecs: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray]:
        matches = self.index.search(vecs, k)
        keys = np.atleast_2d(np.asarray(matches.keys, dtype=np.int64))
        dists = np.atleast_2d(np.asarray(matches.distances, dtype=np.float32))
        # usearch cos distance = 1 - cosine similarity
        return keys, 1.0 - dists


class LexicalIndex:
    SUBDIR = "bm25"

    def __init__(self, retriever):
        self.retriever = retriever

    @classmethod
    def build(cls, texts: list[str], out_dir: Path | str) -> "LexicalIndex":
        import bm25s

        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        tokens = bm25s.tokenize(texts, stopwords="en", show_progress=False)
        retriever = bm25s.BM25()
        retriever.index(tokens, show_progress=False)
        retriever.save(str(out_dir / cls.SUBDIR))
        return cls(retriever)

    @classmethod
    def load(cls, dir: Path | str) -> "LexicalIndex":
        import bm25s

        # in-RAM load; mmap page-faults cost ~150ms per query at 1M docs
        retriever = bm25s.BM25.load(str(Path(dir) / cls.SUBDIR), mmap=False)
        try:
            # numba scorer takes bm25 from ~145ms to under 1ms on 950K
            # docs; one dummy retrieve pays the JIT cost here at load time
            retriever.backend = "numba"  # activate compiles, this selects
            retriever.activate_numba_scorer()
            warmup = bm25s.tokenize(["warmup"], stopwords="en", show_progress=False)
            retriever.retrieve(warmup, k=1, show_progress=False)
        except Exception as exc:  # noqa: BLE001 numpy backend still works
            import sys

            print(f"bm25 numba activation failed, numpy fallback: {exc}",
                  file=sys.stderr)
        return cls(retriever)

    def search(self, text: str, k: int) -> tuple[np.ndarray, np.ndarray]:
        import bm25s

        empty = (np.empty(0, dtype=np.int64), np.empty(0, dtype=np.float32))
        tokens = bm25s.tokenize([text], stopwords="en", show_progress=False)
        # a pure-devanagari query shares no vocab with the english index
        # and tokenizes to nothing; retrieve raises on that, so hand the
        # fusion an empty result and let the dense strategies carry it
        if not tokens.ids or not tokens.ids[0]:
            return empty
        k = min(k, self.retriever.scores["num_docs"])
        try:
            ids, scores = self.retriever.retrieve(tokens, k=k, show_progress=False)
        except Exception:  # noqa: BLE001
            return empty
        # zero-score padding means no vocab overlap; junk ranks would
        # still count in rrf fusion, so drop them
        mask = scores[0] > 0
        return ids[0][mask].astype(np.int64), scores[0][mask].astype(np.float32)


def map_to_parents(
    child_ids: np.ndarray, child_scores: np.ndarray, parent_rows: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Collapse child hits onto parent rows, keeping each parent's best score.

    Inputs are rank-ordered (best first); output preserves that order.
    """
    seen: dict[int, float] = {}
    order: list[int] = []
    for pid, score in zip(parent_rows.tolist(), child_scores.tolist()):
        if pid not in seen:
            seen[pid] = score
            order.append(pid)
    ids = np.asarray(order, dtype=np.int64)
    scores = np.asarray([seen[p] for p in order], dtype=np.float32)
    return ids, scores
