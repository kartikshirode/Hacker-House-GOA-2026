"""Per-strategy retrieval timings on the full corpus."""

import statistics
import time

from vaani.pipeline_text import PipelineConfig, Runtime

runtime = Runtime(PipelineConfig(
    corpus_dir="data/corpus/hin_val", index_root="indexes/hin_val",
))
queries = [
    "what is a corporation", "who wrote silent spring",
    "average temperature in goa december", "symptoms of vitamin d deficiency",
    "how long does a passport take", "capital of maharashtra",
] * 4

per_strategy: dict[str, list[float]] = {}
totals = []
for q in queries:
    vec = runtime.embedder.encode_queries([q])[0]
    t0 = time.perf_counter()
    result = runtime.retriever.retrieve(q, vec, k=10)
    totals.append((time.perf_counter() - t0) * 1000)
    for name, ms in result.timings_ms.items():
        per_strategy.setdefault(name, []).append(ms)

for name, samples in sorted(per_strategy.items()):
    print(f"{name:<16} p50 {statistics.median(samples):7.1f}ms  max {max(samples):7.1f}ms")
print(f"{'total':<16} p50 {statistics.median(totals):7.1f}ms  max {max(totals):7.1f}ms")
