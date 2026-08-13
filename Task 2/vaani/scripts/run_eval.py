"""Replay corpus queries through the pipeline; report quality + latency.

  uv run python scripts/run_eval.py --corpus data/subset/hin_val_100k \
      --indexes indexes/hin_val_100k --n 500

Writes reports/eval_<timestamp>.json and prints a summary table.
Retrieval quality is scored on answerable queries (those with qrels),
abstention quality on the no-answer ones. Latency covers the full
pipeline run per query, extractive path, single process, warm model.
"""

from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict
from pathlib import Path

import duckdb

from vaani.eval import mrr_at_k, percentiles, recall_at_k
from vaani.harness import Refusal
from vaani.pipeline_text import PipelineConfig, Runtime, build_text_pipeline


def load_eval_queries(corpus: Path, n: int) -> tuple[list[dict], dict[int, set[str]]]:
    con = duckdb.connect()
    rows = con.execute(
        f"""
        SELECT query_id, query, eng_query, query_type
        FROM '{(corpus / 'queries.parquet').as_posix()}'
        ORDER BY hash(query_id) LIMIT {n}
        """
    ).fetchall()
    queries = [
        {"query_id": r[0], "query": r[1], "eng_query": r[2], "query_type": r[3]}
        for r in rows
    ]
    qrels: dict[int, set[str]] = defaultdict(set)
    for qid, pid in con.execute(
        f"SELECT query_id, passage_id FROM '{(corpus / 'qrels.parquet').as_posix()}'"
    ).fetchall():
        qrels[qid].add(pid)
    return queries, qrels


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default="data/subset/hin_val_100k")
    ap.add_argument("--indexes", default="indexes/hin_val_100k")
    ap.add_argument("--n", type=int, default=500)
    ap.add_argument("--hindi", action="store_true", help="query with hindi text instead of english")
    ap.add_argument("--strategies", default=None, help="comma list, default all built")
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--abstain-threshold", type=float, default=0.25)
    args = ap.parse_args()

    corpus = Path(args.corpus)
    strategies = args.strategies.split(",") if args.strategies else None
    runtime = Runtime(PipelineConfig(
        corpus_dir=str(corpus), index_root=args.indexes, k=args.k,
        abstain_threshold=args.abstain_threshold, strategies=strategies,
    ))
    pipeline = build_text_pipeline(runtime)
    queries, qrels = load_eval_queries(corpus, args.n)
    print(f"replaying {len(queries)} queries "
          f"({sum(1 for q in queries if q['query_id'] in qrels)} answerable)")

    mrrs, recalls = [], []
    totals_ms: list[float] = []
    stage_ms: dict[str, list[float]] = defaultdict(list)
    refused_answerable = 0
    refused_noanswer = 0
    n_noanswer = 0
    per_type: dict[str, list[float]] = defaultdict(list)

    t_wall = time.perf_counter()
    for q in queries:
        text = q["query"] if args.hindi else q["eng_query"]
        ctx = {"query": text}
        result = pipeline.run(ctx)
        totals_ms.append(result.total_ms)
        for e in result.trace:
            stage_ms[e.stage].append(e.dur_ms)

        gold = qrels.get(q["query_id"], set())
        refused = isinstance(result.answer, Refusal)
        if gold:
            retrieval = ctx.get("retrieval")
            ranked = [h.passage_id for h in retrieval.hits] if retrieval else []
            mrr = mrr_at_k(ranked, gold, k=args.k)
            mrrs.append(mrr)
            recalls.append(recall_at_k(ranked, gold, k=args.k))
            per_type[q["query_type"]].append(mrr)
            if refused:
                refused_answerable += 1
        else:
            n_noanswer += 1
            if refused:
                refused_noanswer += 1
    wall_s = time.perf_counter() - t_wall

    refused_total = refused_answerable + refused_noanswer
    abst_precision = refused_noanswer / refused_total if refused_total else 0.0
    abst_recall = refused_noanswer / n_noanswer if n_noanswer else 0.0

    report = {
        "config": {
            "corpus": str(corpus), "indexes": args.indexes, "n": len(queries),
            "hindi_queries": args.hindi, "strategies": strategies or "all",
            "k": args.k, "abstain_threshold": args.abstain_threshold,
        },
        "retrieval": {
            "n_answerable": len(mrrs),
            "mrr_at_k": round(sum(mrrs) / len(mrrs), 4) if mrrs else 0.0,
            "recall_at_k": round(sum(recalls) / len(recalls), 4) if recalls else 0.0,
            "mrr_by_query_type": {
                t: round(sum(v) / len(v), 4) for t, v in sorted(per_type.items())
            },
        },
        "abstention": {
            "n_noanswer": n_noanswer,
            "refused_noanswer": refused_noanswer,
            "refused_answerable": refused_answerable,
            "precision": round(abst_precision, 4),
            "recall": round(abst_recall, 4),
        },
        "latency_ms": {
            "total": percentiles(totals_ms),
            "per_stage": {s: percentiles(v) for s, v in sorted(stage_ms.items())},
            "wall_seconds": round(wall_s, 1),
            "qps": round(len(queries) / wall_s, 1),
        },
    }

    out = Path("reports")
    out.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    path = out / f"eval_{stamp}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    r, a, l = report["retrieval"], report["abstention"], report["latency_ms"]
    print(f"\nMRR@{args.k}={r['mrr_at_k']}  recall@{args.k}={r['recall_at_k']} "
          f"on {r['n_answerable']} answerable")
    print(f"abstention precision={a['precision']} recall={a['recall']} "
          f"(refused {a['refused_answerable']} answerable)")
    print(f"latency total ms: {l['total']}")
    for s, p in l["per_stage"].items():
        print(f"  {s:<14} {p}")
    print(f"wall {l['wall_seconds']}s  ({l['qps']} q/s)  -> {path}")


if __name__ == "__main__":
    main()
