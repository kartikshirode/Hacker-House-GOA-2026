"""Query-time strategy adapters over the index primitives.

Each strategy exposes search_rows(query_text, query_vec, k) returning
(row_offsets, scores) so the retriever can fuse them without knowing
what lives underneath.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from vaani.indexes import DenseIndex, LexicalIndex, map_to_parents


class PassageDenseStrategy:
    name = "passage_dense"

    def __init__(self, dense: DenseIndex):
        self.dense = dense

    def search_rows(self, query_text, query_vec, k):
        ids, scores = self.dense.search(query_vec[None, :], k)
        return ids[0], scores[0]


class SentenceDenseStrategy:
    name = "sentence_dense"

    def __init__(self, dense: DenseIndex, parents: np.ndarray):
        self.dense = dense
        self.parents = parents

    def search_rows(self, query_text, query_vec, k):
        # overfetch children since several sentences share one parent
        ids, scores = self.dense.search(query_vec[None, :], k * 3)
        parent_rows = self.parents[ids[0]]
        rows, best = map_to_parents(ids[0], scores[0], parent_rows)
        return rows[:k], best[:k]


class LexicalStrategy:
    name = "bm25_eng"

    def __init__(self, lex: LexicalIndex):
        self.lex = lex

    def search_rows(self, query_text, query_vec, k):
        return self.lex.search(query_text, k)


def load_strategies(index_root: Path | str) -> dict:
    """Load every built strategy directory under index_root."""
    index_root = Path(index_root)
    out: dict = {}
    for d in sorted(index_root.iterdir()):
        meta_file = d / "meta.json"
        if not meta_file.exists():
            continue
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        kind = meta["strategy"]
        if kind == "passage":
            out["passage_dense"] = PassageDenseStrategy(DenseIndex.load(d))
            if (d / LexicalIndex.SUBDIR).exists():
                out["bm25_eng"] = LexicalStrategy(LexicalIndex.load(d))
        elif kind == "sentence":
            parents = np.load(d / "parents.npy")
            out["sentence_dense"] = SentenceDenseStrategy(DenseIndex.load(d), parents)
    return out
