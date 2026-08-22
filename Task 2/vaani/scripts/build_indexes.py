"""Build query-time index artifacts for one corpus.

Strategies:
  passage   dense HNSW over english passage text + bm25 lexical index
  sentence  dense HNSW over individual sentences with parent mapping

Row offsets refer to the passage table sorted by passage_id, matching
PassageStore. Usage:

  uv run python scripts/build_indexes.py --corpus data/subset/hin_val_100k \
      --out indexes/hin_val_100k --strategy passage
  uv run python scripts/build_indexes.py --corpus data/subset/hin_val_100k \
      --out indexes/hin_val_100k --strategy sentence
"""

import argparse
import json
import re
import time
from pathlib import Path

import duckdb
import numpy as np

from vaani.embed import Embedder
from vaani.indexes import DenseIndex, LexicalIndex

SENT_SPLIT = re.compile(r"(?<=[.!?।])\s+")
MIN_SENT_CHARS = 15


def load_passages(corpus: Path) -> tuple[list[str], list[str]]:
    con = duckdb.connect()
    rows = con.execute(
        f"SELECT passage_id, eng_text FROM '{(corpus / 'passages.parquet').as_posix()}' ORDER BY passage_id"
    ).fetchall()
    return [r[0] for r in rows], [r[1] for r in rows]


def encode_with_progress(embedder, texts, batch_size, checkpoint):
    """Embed in chunks, printing progress and check-pointing as it goes.

    The plain one-shot call prints nothing for hours and saves nothing
    until it finishes, so a Slurm time limit or a dropped session throws
    the whole run away and you cannot tell a slow job from a hung one.
    A re-run picks up the finished chunk file instead of starting over.
    """
    if checkpoint.exists():
        vecs = np.load(checkpoint)
        if len(vecs) == len(texts):
            print(f"resuming from {checkpoint} ({len(vecs):,} vectors)")
            return vecs
        print(f"{checkpoint} has {len(vecs):,} vectors for {len(texts):,} texts, rebuilding")

    chunk = max(batch_size * 40, 10_000)
    parts, done, t0 = [], 0, time.perf_counter()
    for i in range(0, len(texts), chunk):
        parts.append(embedder.encode_passages(texts[i:i + chunk], batch_size=batch_size))
        done += len(parts[-1])
        rate = done / (time.perf_counter() - t0)
        eta = (len(texts) - done) / rate if rate else 0
        print(f"  embedded {done:,}/{len(texts):,} "
              f"({100 * done / len(texts):.1f}%)  {rate:.0f}/s  eta {eta / 60:.1f} min",
              flush=True)
    vecs = np.concatenate(parts) if len(parts) > 1 else parts[0]
    np.save(checkpoint, vecs)
    return vecs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--strategy", required=True, choices=["passage", "sentence"])
    ap.add_argument("--model", default="intfloat/multilingual-e5-small")
    ap.add_argument("--batch", type=int, default=256)
    args = ap.parse_args()

    corpus = Path(args.corpus)
    out = Path(args.out) / args.strategy
    out.mkdir(parents=True, exist_ok=True)

    ids, eng = load_passages(corpus)
    print(f"{len(ids):,} passages loaded")
    np.save(out / "passage_ids.npy", np.array(ids))

    embedder = Embedder(args.model)
    t0 = time.perf_counter()

    if args.strategy == "passage":
        vecs = encode_with_progress(embedder, eng, args.batch, out / "vecs.npy")
        embed_s = time.perf_counter() - t0
        print(f"embedded in {embed_s:.0f}s")
        DenseIndex.build(vecs, out)
        LexicalIndex.build(eng, out)
        n_units = len(eng)
    else:
        sentences: list[str] = []
        parents: list[int] = []
        for row, text in enumerate(eng):
            for sent in SENT_SPLIT.split(text or ""):
                if len(sent.strip()) >= MIN_SENT_CHARS:
                    sentences.append(sent.strip())
                    parents.append(row)
        print(f"{len(sentences):,} sentences from {len(eng):,} passages")
        vecs = embedder.encode_passages(sentences, batch_size=args.batch)
        embed_s = time.perf_counter() - t0
        print(f"embedded in {embed_s:.0f}s")
        DenseIndex.build(vecs, out)
        np.save(out / "parents.npy", np.asarray(parents, dtype=np.int64))
        n_units = len(sentences)

    build_s = time.perf_counter() - t0
    meta = {
        "strategy": args.strategy,
        "model": args.model,
        "dims": int(vecs.shape[1]),
        "units": int(n_units),
        "passages": len(ids),
        "corpus": str(corpus),
        "build_seconds": round(build_s, 1),
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"done in {build_s:.0f}s -> {out}")


if __name__ == "__main__":
    main()
