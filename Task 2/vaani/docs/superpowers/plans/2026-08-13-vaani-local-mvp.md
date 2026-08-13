# Vaani Local MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A text-query RAG pipeline over a 100K-passage Hindi subset that runs end to end on the local RTX 4060 with per-stage tracing, fused dense+BM25 retrieval and an eval runner producing MRR@10 plus P50/P70/P100 latency.

**Architecture:** Staged pipeline harness (typed stages, timeouts, fallbacks, trace events) wrapping embed → retrieve (HNSW + BM25 + RRF) → answer (extractive now, vLLM later). Index builders are offline scripts; the harness only ever does cheap query-time work.

**Tech Stack:** Python 3.12, uv, sentence-transformers (multilingual-e5-small), usearch (HNSW), bm25s, pydantic v2, duckdb, pytest.

**Spec:** docs/design.md

## Global Constraints

- All heavy work happens at index time; query-time budget is 200ms total, retrieval portion under 25ms.
- Every pipeline stage declares timeout + fallback; no stage may raise to the caller.
- Latency measured with time.perf_counter_ns at stage boundaries, stored per request.
- Local GPU runs must stay in the 5-10 minute range; anything longer targets the cluster.
- e5 models require "query: " / "passage: " prefixes; forgetting them silently wrecks recall.
- No em or en dashes in any prose written to files.

---

### Task 1: Embedding wrapper

**Files:**
- Create: `src/vaani/embed.py`
- Test: `tests/test_embed.py`

**Interfaces:**
- Produces: `Embedder(model_name: str = "intfloat/multilingual-e5-small", device: str | None = None)` with `.encode_queries(texts: list[str]) -> np.ndarray` and `.encode_passages(texts: list[str]) -> np.ndarray`, both returning float32 L2-normalized arrays shaped (n, 384).

- [ ] Write failing test: encode_queries returns (2, 384) float32, unit norm, and differs from encode_passages for identical text (prefix effect).
- [ ] Run `uv run pytest tests/test_embed.py -v`, expect ImportError/AttributeError.
- [ ] Implement with sentence-transformers, prefixes added internally, `normalize_embeddings=True`.
- [ ] Run test, expect PASS (first run downloads ~450MB model).
- [ ] Commit "Add e5 embedding wrapper with query/passage prefixes".

### Task 2: Local subset builder

**Files:**
- Create: `scripts/make_subset.py`

**Interfaces:**
- Produces: `data/subset/hin_val_100k/{passages,queries,qrels}.parquet` with identical schemas to the full corpus tables. Selection rule: keep every passage referenced by a qrel of the sampled queries plus random fill to the target size; sample 5,000 queries stratified by query_type including no-answer ones.

- [ ] Write the script with duckdb: sample queries (setseed(0.42) for reproducibility), collect their qrel passages, random-fill remaining passages to 100K, write three parquets plus a stats line.
- [ ] Run it; verify printed counts: 5,000 queries, 100,000 passages, qrel coverage 100% for answerable sampled queries.
- [ ] Commit "Add stratified 100k subset builder for local runs".

### Task 3: Dense + lexical index builders

**Files:**
- Create: `scripts/build_indexes.py`, `src/vaani/indexes.py`
- Test: `tests/test_indexes.py`

**Interfaces:**
- `indexes.py` produces: `DenseIndex.load(dir) / .search(vecs, k) -> (ids, scores)` wrapping usearch; `LexicalIndex.load(dir) / .search(text, k)` wrapping bm25s; both return passage row offsets aligned to a shared `passage_ids.npy`.
- `build_indexes.py` consumes corpus parquet + Embedder, writes `indexes/<name>/` artifacts: `dense.usearch`, `bm25/`, `passage_ids.npy`, `meta.json` (strategy name, model, dims, count, build time).

- [ ] Write failing test using 50 synthetic passages: build tiny index in tmpdir, search returns the planted near-duplicate first.
- [ ] Run test, expect failure.
- [ ] Implement usearch (cosine, f16 storage) + bm25s (english tokenizer for eng_text; hindi handled later by dense-only).
- [ ] Run test, expect PASS.
- [ ] Run `build_indexes.py --corpus data/subset/hin_val_100k --strategy passage` on GPU, confirm under 10 minutes, record build time in meta.json.
- [ ] Commit "Add dense and bm25 index builders plus loaders".

### Task 4: Sentence-level small-to-big index

**Files:**
- Modify: `scripts/build_indexes.py`, `src/vaani/indexes.py`
- Test: `tests/test_indexes.py` (extend)

**Interfaces:**
- Strategy `sentence` writes the same artifact layout plus `parents.npy` (sentence row -> passage row). `DenseIndex.search` output passes through `map_to_parents(ids) -> passage rows, deduped, best-score-kept`.

- [ ] Failing test: passage whose second sentence matches the query is retrieved via sentence index and mapped back to the passage id.
- [ ] Implement sentence splitting (regex on danda + latin punctuation: `[।.!?]`), skip sentences under 15 chars, embed, build, map.
- [ ] Test passes; build sentence index for the subset locally.
- [ ] Commit "Add sentence-level index with parent passage mapping".

### Task 5: Fused retriever

**Files:**
- Create: `src/vaani/retriever.py`
- Test: `tests/test_retriever.py`

**Interfaces:**
- Produces: `Retriever(indexes: dict[str, LoadedStrategy], passages: PassageStore)` with `.retrieve(query_text: str, query_vec: np.ndarray, k: int = 10, strategies: list[str] | None = None) -> RetrievalResult`. `RetrievalResult` (pydantic): `hits: list[Hit]` where `Hit = {passage_id, eng_text, tr_text, score, source_strategies}`, plus `confidence: float` (top RRF score) and `timings_ms: dict[str, float]`.
- RRF: `score = sum(1/(60 + rank_s))` over each strategy's ranked list.

- [ ] Failing test with two fake strategies returning known rankings: RRF order and source_strategies attribution correct; empty-result strategy tolerated.
- [ ] Implement; PASS; commit "Add RRF fusion retriever".

### Task 6: Harness core

**Files:**
- Create: `src/vaani/harness.py`
- Test: `tests/test_harness.py`

**Interfaces:**
- Produces: `Stage` (name, run(ctx) -> ctx delta, timeout_ms, fallback: Stage | None, retries: int = 0), `Pipeline(stages).run(request) -> PipelineResult`, `PipelineResult` carrying `answer: AnswerPayload | Refusal`, `trace: list[StageEvent]`, `total_ms: float`. `StageEvent = {stage, started_ns, dur_ms, outcome: ok|timeout|error|fallback, detail}`.
- Timeouts via `concurrent.futures` with a shared worker pool; a timed-out stage's fallback runs synchronously; if no fallback, pipeline short-circuits to Refusal(reason_code).

- [ ] Failing tests: (a) happy path records ok events with durations; (b) stage exceeding timeout_ms triggers fallback and marks outcome fallback; (c) stage raising without fallback yields Refusal with reason "stage_error:<name>" and never raises.
- [ ] Implement; PASS; commit "Add staged pipeline harness with timeouts, fallbacks and tracing".

### Task 7: Text pipeline assembly + extractive answerer

**Files:**
- Create: `src/vaani/pipeline_text.py`, `src/vaani/answer_extractive.py`
- Test: `tests/test_pipeline_text.py`

**Interfaces:**
- `answer_extractive.answer(hits, query) -> AnswerPayload` picks the best sentence from the top hit (embedding-free heuristic: token overlap + position), returns `{text, passage_ids, kind: "extractive"}`.
- `build_text_pipeline(cfg) -> Pipeline` wiring stages: `guard_input` (stub allowing all, interface final: returns GuardVerdict), `embed_query`, `retrieve`, `answer` (extractive for now), `guard_output` (stub). Confidence below `cfg.abstain_threshold` short-circuits to Refusal("low_confidence").
- Produces the CLI: `uv run python -m vaani.ask "query text" --corpus data/subset/hin_val_100k` printing answer + trace table.

- [ ] Failing integration test on the subset indexes (marked `@pytest.mark.slow`): known answerable query returns non-empty answer with at least one qrel passage in top-10; nonsense off-corpus query returns Refusal.
- [ ] Implement, wire, PASS.
- [ ] Run the CLI once, paste the trace table into the commit body.
- [ ] Commit "Wire text query pipeline with extractive answers and abstention".

### Task 8: Eval + latency runner

**Files:**
- Create: `scripts/run_eval.py`, `src/vaani/eval.py`
- Test: `tests/test_eval.py`

**Interfaces:**
- `eval.mrr_at_k(ranked_ids, gold_ids, k=10) -> float`; `eval.percentiles(samples_ms) -> {p50, p70, p90, p100}`.
- `run_eval.py --corpus ... --n 500 --strategies passage,sentence` replays queries through the pipeline, writes `reports/eval_<timestamp>.json` (per-strategy MRR@10, recall@10, abstention precision/recall on no-answer gold, latency percentiles overall and per stage) and prints a markdown table.

- [ ] Failing unit tests for mrr_at_k and percentiles (hand-computed cases, p100 = max).
- [ ] Implement metrics; PASS.
- [ ] Run 500-query eval locally (CPU search path, GPU embed), confirm it completes and produces sane numbers; keep the JSON.
- [ ] Commit "Add eval runner reporting retrieval quality and latency percentiles".

---

## Follow-up plans (separate documents, written when the cluster is known)

- Phase B (Aug 14-16): full 950K index on cluster, embedding bake-off (e5-small vs bge-m3 vs embeddinggemma), fixed-window + semantic-merge + metadata strategies, vLLM generation stage + prompt, HHEM groundedness stage, Prompt-Guard input stage, Sarvam realtime STT client + speculative retrieval, FastAPI WS server + web UI.
- Phase C (Aug 17-20): full benchmark + ablation report, guardrail threshold tuning on no-answer gold, tunnel deployment for the live link, demo polish, videos, submission form. Buffer through Aug 22.

## Self-review notes

Spec coverage: chunking variety lands in Tasks 3-5 plus Phase B strategies; harness requirement in Task 6; guardrails partially stubbed here (gates 2-3) with models in Phase B; latency analytics in Task 8. Voice is Phase B by design since STT keys arrive with the user. Types named identically across Tasks 5-8 (RetrievalResult, Hit, AnswerPayload, Refusal, GuardVerdict). No placeholders beyond explicitly deferred Phase B/C scope.
