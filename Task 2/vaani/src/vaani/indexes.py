"""Index primitives: dense HNSW (usearch), lexical BM25 (bm25s).

Both search interfaces return row offsets into the corpus passage table,
never md5 ids; the caller owns the offset-to-passage mapping. Artifacts
for one strategy live together in one directory.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np


class DenseIndex:
    FILE = "dense.usearch"

    def __init__(self, index):
        self.index = index

    @classmethod
    def build(cls, vectors: np.ndarray, out_dir: Path | str) -> "DenseIndex":
        from usearch.index import Index

        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        idx = Index(ndim=vectors.shape[1], metric="cos", dtype="f16")
        idx.add(np.arange(len(vectors), dtype=np.int64), vectors)
        idx.save(str(out_dir / cls.FILE))
        return cls(idx)

    @classmethod
    def load(cls, dir: Path | str) -> "DenseIndex":
        from usearch.index import Index

        idx = Index.restore(str(Path(dir) / cls.FILE))
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

        tokens = bm25s.tokenize([text], stopwords="en", show_progress=False)
        k = min(k, self.retriever.scores["num_docs"])
        ids, scores = self.retriever.retrieve(tokens, k=k, show_progress=False)
        return ids[0].astype(np.int64), scores[0].astype(np.float32)


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
