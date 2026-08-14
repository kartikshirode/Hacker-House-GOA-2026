"""Single-query embed latency on CPU, for the login-node serving plan."""

import time

from vaani.embed import Embedder

e = Embedder(device="cpu")
e.encode_queries(["warmup"] )
t0 = time.perf_counter()
n = 30
for _ in range(n):
    e.encode_queries(["what is the capital of maharashtra"])
print(f"cpu single query embed: {(time.perf_counter() - t0) / n * 1000:.1f}ms")
