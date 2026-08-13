"""Query and passage embedding on top of multilingual-e5-small.

e5 models are trained with "query: " and "passage: " prefixes; skipping
them quietly degrades retrieval, so the prefixes live here and nowhere
else in the codebase.
"""

from __future__ import annotations

import numpy as np

DEFAULT_MODEL = "intfloat/multilingual-e5-small"


class Embedder:
    def __init__(self, model_name: str = DEFAULT_MODEL, device: str | None = None):
        # imported lazily so config/tests that never embed stay fast
        from sentence_transformers import SentenceTransformer

        self.model_name = model_name
        self.model = SentenceTransformer(model_name, device=device)

    def _encode(self, texts: list[str], prefix: str, batch_size: int) -> np.ndarray:
        vecs = self.model.encode(
            [prefix + t for t in texts],
            batch_size=batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return np.asarray(vecs, dtype=np.float32)

    def encode_queries(self, texts: list[str], batch_size: int = 32) -> np.ndarray:
        return self._encode(texts, "query: ", batch_size)

    def encode_passages(self, texts: list[str], batch_size: int = 256) -> np.ndarray:
        return self._encode(texts, "passage: ", batch_size)
