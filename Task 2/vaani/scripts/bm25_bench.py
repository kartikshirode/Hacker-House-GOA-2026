"""Compare bm25s scoring backends on the full corpus index."""

import statistics
import time

import bm25s

r = bm25s.BM25.load("indexes/hin_val/passage/bm25", mmap=False)
print("backend attrs:", [m for m in dir(r) if "numba" in m.lower() or "backend" in m.lower()])
print("current backend:", getattr(r, "backend", "unknown"))

queries = ["what is a corporation", "average temperature goa december",
           "symptoms vitamin d deficiency", "capital of maharashtra"] * 3


def bench(label):
    times = []
    for q in queries:
        tokens = bm25s.tokenize([q], stopwords="en", show_progress=False)
        t0 = time.perf_counter()
        r.retrieve(tokens, k=10, show_progress=False)
        times.append((time.perf_counter() - t0) * 1000)
    print(f"{label}: p50 {statistics.median(times):.1f}ms max {max(times):.1f}ms")


bench("default")
try:
    r.backend = "numba"
    if hasattr(r, "activate_numba_scorer"):
        r.activate_numba_scorer()
    bench("numba warm1")
    bench("numba warm2")
except Exception as exc:  # noqa: BLE001
    print("numba failed:", exc)
