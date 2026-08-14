# Vaani

Voice-enabled RAG over `ai4bharat/MSMARCO-XI`, built for the HH Goa 2026 Task 2 shortlisting. You speak a question in Hindi or English, Sarvam transcribes it while you talk, retrieval runs against a hybrid index of 950K passages and a grounded answer streams back token by token. The whole post-transcript path runs under 200ms through P90, measured on 1000 real queries.

Design notes live in [docs/design.md](docs/design.md). Plans and review rounds are under [docs/superpowers/plans/](docs/superpowers/plans/).

## Pipeline

```
voice ──> Sarvam realtime STT ──> guard ──> embed ──> retrieve ──> abstain gate ──> answer ──> groundedness gate
              (partials fire            (guard rides     (HNSW + BM25,                (streams tokens,
               speculative retrieval)    along, no wall    RRF fusion)                 NO_ANSWER contract)
                                         time)
```

Every stage runs inside a harness with timeouts, retries and fallbacks; a blown generation deadline degrades to a sub-10ms extractive answer instead of blowing the budget. Each request carries a per-stage trace, so the latency numbers below come from the same code path the demo uses.

## Measured results

Full 950K-passage corpus, 1000 real queries, generation and guards on. Hardware: one Blackwell 1g.24gb MIG slice serving Qwen3-0.6B on vLLM 0.27.1 with ngram speculative decoding.

| | P50 | P70 | P90 | P100 |
|---|---|---|---|---|
| English pipeline, end to end | 122.0ms | 139.2ms | 169.5ms | 357.0ms |
| Hindi pipeline, end to end | 102.9ms | 149.3ms | 188.5ms | 530.0ms |

Quality on the same runs: MRR@10 0.4066, recall@10 0.7417 on answerable queries, token F1 0.268 against reference answers, zero truncated answers. P100 is two outliers out of a thousand; the reports keep them visible rather than trimming them.

Speculative decoding earns its place: english generation p50 dropped from 84.7ms to 43.5ms, hindi from 242ms to 131ms, with byte-identical answers. RAG answers copy context spans, which is the best case for prompt lookup. On the laptop fallback (RTX 4060, llama.cpp), the same model generates in 77ms.

Abstention is layered and measured: retrieval-confidence gate, model NO_ANSWER contract, HHEM groundedness check. The eval reports itemize every refusal reason; roughly 45% of MSMARCO queries have no answer in the corpus, and those double as abstention ground truth.

All raw reports are committed under [reports/](reports/), labeled by machine.

## Chunking and retrieval

Three strategies, ablated head to head on the full corpus (reports committed):

- passage-level dense, multilingual-e5-small in a usearch HNSW index
- sentence-level dense with parent passage mapping and overfetch
- lexical BM25 over the parallel English text, numba scorer (145ms down to under 1ms at 950K docs)

Passage plus BM25 fused with reciprocal rank fusion wins; sentence-level underperforms on this corpus, which the design predicted for short web passages. The losing config stays in the repo because the ablation is the point, not just the winner.

## Guardrails

Four gates, each honest about its blind spots: a prompt-injection classifier on input (english-only by training, so it steps aside for devanagari and says so in the trace), the retrieval-confidence abstain gate, the model's own NO_ANSWER contract, and HHEM-2.1 groundedness scoring on generative answers (also english-scoped). Guard checks that cannot run mark the answer unchecked rather than silently passing it.

## Layout

- `src/vaani/harness.py` staged pipeline core: timeouts, fallbacks, retries, tracing
- `src/vaani/pipeline_text.py` assembles the pipeline, warms every component at boot
- `src/vaani/embed.py` multilingual-e5-small wrapper
- `src/vaani/indexes.py` usearch HNSW and bm25s primitives
- `src/vaani/strategies.py` query-time strategies, fail-soft loading
- `src/vaani/retriever.py` reciprocal rank fusion across strategies
- `src/vaani/answer_generative.py` OpenAI-compatible client, token streaming, language-aware caps
- `src/vaani/answer_extractive.py` model-free answer floor, sub-10ms
- `src/vaani/guards.py` input and groundedness gates
- `src/vaani/guard_service.py` GPU sidecar serving both guard models
- `src/vaani/stt.py` / `stt_realtime.py` Sarvam REST and streaming clients, spend ledger, mock mode
- `src/vaani/server.py` FastAPI app: REST, websocket voice with speculative retrieval, static UI
- `web/` the demo UI: mic streaming over AudioWorklet, live partials, typed tokens, latency waterfall
- `scripts/` corpus build, index build, eval runner, generation bench
- `slurm/` cluster serving jobs, readiness-gated

## Quickstart

Needs Python 3.12 and uv. First run downloads the e5 model (about 450MB).

```
uv sync
uv run python scripts/build_corpus.py --lang hin --split val
uv run python scripts/build_indexes.py --corpus data/corpus/hin_val --out indexes/hin_val --strategy passage
uv run python scripts/run_eval.py --corpus data/corpus/hin_val --indexes indexes/hin_val --n 500
```

Serve the demo (generation optional; without it answers are extractive):

```
uv run uvicorn vaani.server:create_default_app --factory --port 8000
```

Point `VAANI_GENERATION_URL` at any OpenAI-compatible endpoint (vLLM on the cluster, llama-server locally) and `VAANI_GUARD_URL` at the guard sidecar. `SARVAM_API_KEY` in `.env` enables voice; `VAANI_STT_MOCK=1` runs voice endpoints without spending credits.

Tests: `uv run pytest` (60 tests).

## Dataset

MSMARCO-XI is MS MARCO QnA machine-translated into 14 Indic languages by AI4Bharat (arXiv 2506.01615). Each row keeps the English and translated passages side by side, with relevance flags and reference answers. The Hindi validation slice used here has 97,941 queries and 950,721 unique passages.
