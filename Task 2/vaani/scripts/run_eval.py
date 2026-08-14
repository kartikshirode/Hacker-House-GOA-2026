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
from collections import Counter, defaultdict
from pathlib import Path

import duckdb

from vaani.answer_generative import MAX_TOKENS_EN, MAX_TOKENS_HI
from vaani.eval import mrr_at_k, percentiles, recall_at_k, token_f1
from vaani.harness import Refusal
from vaani.pipeline_text import PipelineConfig, Runtime, build_text_pipeline


def load_eval_queries(corpus: Path, n: int) -> tuple[list[dict], dict[int, set[str]]]:
    con = duckdb.connect()
    rows = con.execute(
        f"""
        SELECT query_id, query, eng_query, query_type, answer, eng_answer
        FROM '{(corpus / 'queries.parquet').as_posix()}'
        ORDER BY hash(query_id) LIMIT {n}
        """
    ).fetchall()
    queries = [
        {"query_id": r[0], "query": r[1], "eng_query": r[2], "query_type": r[3],
         "answer": r[4], "eng_answer": r[5]}
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
    ap.add_argument("--abstain-threshold", type=float, default=0.85)
    ap.add_argument("--generation-url", default=None,
                    help="openai-compatible endpoint; omit for extractive answers")
    ap.add_argument("--guard-url", default=None,
                    help="guard sidecar endpoint; omit for permissive stubs")
    args = ap.parse_args()

    corpus = Path(args.corpus)
    strategies = args.strategies.split(",") if args.strategies else None
    runtime = Runtime(PipelineConfig(
        corpus_dir=str(corpus), index_root=args.indexes, k=args.k,
        abstain_threshold=args.abstain_threshold, strategies=strategies,
        generation_url=args.generation_url,
        guard_url=args.guard_url,
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
    answer_kinds: Counter[str] = Counter()
    refusal_reasons: Counter[str] = Counter()
    stage_outcomes: Counter[str] = Counter()
    fallback_causes: Counter[str] = Counter()
    guard_unchecked: Counter[str] = Counter()
    f1_all: list[float] = []
    f1_generative: list[float] = []

    def fallback_cause(detail: str) -> str:
        # harness fallback detail reads "timeout: ..." or "error: Type: msg"
        if detail.startswith("timeout"):
            return "timeout"
        if detail.startswith("error: "):
            return detail.split(": ")[1] if ": " in detail[7:] else detail[7:]
        return detail or "unknown"

    t_wall = time.perf_counter()
    for q in queries:
        text = q["query"] if args.hindi else q["eng_query"]
        ctx = {"query": text}
        result = pipeline.run(ctx)
        totals_ms.append(result.total_ms)
        for e in result.trace:
            stage_ms[e.stage].append(e.dur_ms)
            if e.outcome != "ok":
                stage_outcomes[f"{e.stage}:{e.outcome}"] += 1
            if e.stage == "answer" and e.outcome == "fallback":
                fallback_causes[fallback_cause(e.detail)] += 1
        for gate in ("guard_input", "guard_output"):
            verdict = ctx.get(gate)
            if verdict is not None and not verdict.checked:
                guard_unchecked[f"{gate}:{verdict.reason}"] += 1

        gold = qrels.get(q["query_id"], set())
        refused = isinstance(result.answer, Refusal)
        if refused:
            refusal_reasons[result.answer.reason_code] += 1
        else:
            answer_kinds[result.answer.kind] += 1
        if gold:
            retrieval = ctx.get("retrieval")
            ranked = [h.passage_id for h in retrieval.hits] if retrieval else []
            mrr = mrr_at_k(ranked, gold, k=args.k)
            mrrs.append(mrr)
            recalls.append(recall_at_k(ranked, gold, k=args.k))
            per_type[q["query_type"]].append(mrr)
            ref = q["answer"] if args.hindi else q["eng_answer"]
            # every answerable query scores: refusals as zero, fallbacks
            # included, so failing more cannot inflate the number
            if refused:
                refused_answerable += 1
                if ref:
                    f1_all.append(0.0)
            elif ref:
                score = token_f1(result.answer.text, ref)
                f1_all.append(score)
                if result.answer.kind == "generative":
                    f1_generative.append(score)
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
            "generation_url": args.generation_url,
            "generation_model": runtime.genclient.model if runtime.genclient else None,
            "max_tokens": {"en": MAX_TOKENS_EN, "hi": MAX_TOKENS_HI},
            "guard_url": args.guard_url,
        },
        "answers": {
            "kinds": dict(answer_kinds),
            "refusal_reasons": dict(refusal_reasons),
            "stage_outcomes": dict(stage_outcomes),
            "fallback_causes": dict(fallback_causes),
            "guard_unchecked": dict(guard_unchecked),
            "token_f1_all_answerable": round(sum(f1_all) / len(f1_all), 4) if f1_all else None,
            "n_f1_all": len(f1_all),
            "token_f1_generative": round(sum(f1_generative) / len(f1_generative), 4) if f1_generative else None,
            "n_f1_generative": len(f1_generative),
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
    ans = report["answers"]
    print(f"\nMRR@{args.k}={r['mrr_at_k']}  recall@{args.k}={r['recall_at_k']} "
          f"on {r['n_answerable']} answerable")
    print(f"abstention precision={a['precision']} recall={a['recall']} "
          f"(refused {a['refused_answerable']} answerable)")
    print(f"answers {ans['kinds']}  refusals {ans['refusal_reasons']}")
    if ans["stage_outcomes"]:
        print(f"stage outcomes (non-ok): {ans['stage_outcomes']}")
    if ans["fallback_causes"]:
        print(f"answer fallback causes: {ans['fallback_causes']}")
    if ans["guard_unchecked"]:
        print(f"guard unchecked: {ans['guard_unchecked']}")
    if ans["token_f1_all_answerable"] is not None:
        print(f"token F1 all answerable = {ans['token_f1_all_answerable']} on {ans['n_f1_all']} "
              f"(generative only = {ans['token_f1_generative']} on {ans['n_f1_generative']})")
    print(f"latency total ms: {l['total']}")
    for s, p in l["per_stage"].items():
        print(f"  {s:<14} {p}")
    print(f"wall {l['wall_seconds']}s  ({l['qps']} q/s)  -> {path}")


if __name__ == "__main__":
    main()
