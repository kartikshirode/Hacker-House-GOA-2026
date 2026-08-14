"""GPU smoke test for one MIG slice: torch, matmul, embed throughput."""

import time

import torch

print("torch", torch.__version__, "cuda", torch.cuda.is_available())
print("device", torch.cuda.get_device_name(0))
props = torch.cuda.get_device_properties(0)
print(f"vram {props.total_memory / 1e9:.1f}GB  sms {props.multi_processor_count}")

x = torch.randn(4096, 4096, device="cuda")
torch.cuda.synchronize()
t0 = time.perf_counter()
for _ in range(20):
    x = x @ x
    x = x / x.norm()
torch.cuda.synchronize()
print(f"20 chained 4096 matmuls: {time.perf_counter() - t0:.2f}s")

from vaani.embed import Embedder  # noqa: E402

e = Embedder(device="cuda")
texts = ["this is a benchmark passage about corporations and law"] * 4096
e.encode_passages(texts[:64])  # warmup
t0 = time.perf_counter()
v = e.encode_passages(texts)
dt = time.perf_counter() - t0
print(f"embed 4096 passages: {dt:.2f}s ({4096 / dt:.0f}/s) -> {v.shape}")

e.encode_queries(["warmup"])
t0 = time.perf_counter()
for _ in range(50):
    e.encode_queries(["single query latency check"])
print(f"single query embed: {(time.perf_counter() - t0) / 50 * 1000:.1f}ms")
