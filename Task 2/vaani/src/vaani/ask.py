"""One-shot CLI: ask the pipeline a question, see answer plus trace.

  uv run python -m vaani.ask "who wrote silent spring" \
      --corpus data/subset/hin_val_100k --indexes indexes/hin_val_100k
"""

from __future__ import annotations

import argparse

from vaani.harness import Refusal
from vaani.pipeline_text import PipelineConfig, Runtime, build_text_pipeline


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--corpus", default="data/subset/hin_val_100k")
    ap.add_argument("--indexes", default="indexes/hin_val_100k")
    ap.add_argument("--k", type=int, default=10)
    args = ap.parse_args()

    runtime = Runtime(PipelineConfig(
        corpus_dir=args.corpus, index_root=args.indexes, k=args.k
    ))
    pipeline = build_text_pipeline(runtime)
    result = pipeline.run({"query": args.query})

    print()
    if isinstance(result.answer, Refusal):
        print(f"REFUSED [{result.answer.reason_code}] {result.answer.message}")
    else:
        print(f"ANSWER ({result.answer.kind}): {result.answer.text}")
        print(f"  sources: {', '.join(result.answer.passage_ids)}")

    print(f"\ntotal {result.total_ms:.1f}ms")
    print(f"{'stage':<14}{'ms':>8}  outcome")
    for e in result.trace:
        print(f"{e.stage:<14}{e.dur_ms:>8.2f}  {e.outcome}{' ' + e.detail if e.detail else ''}")


if __name__ == "__main__":
    main()
