# Vaani

Voice-enabled RAG over `ai4bharat/MSMARCO-XI`, built for the HH Goa 2026 Task 2 shortlisting. You speak a question in Hindi or English, Sarvam transcribes it while you talk, retrieval runs against a passage index and a grounded answer comes back. The whole post-transcript path is budgeted under 200ms.

Design notes live in [docs/design.md](docs/design.md). The current implementation plan is [docs/superpowers/plans/2026-08-13-vaani-local-mvp.md](docs/superpowers/plans/2026-08-13-vaani-local-mvp.md).

## Pipeline

```
voice ──> Sarvam realtime STT ──> guard ──> embed ──> retrieve ──> abstain gate ──> answer ──> groundedness gate
              (partials fire            (query and     (HNSW + BM25,
               speculative retrieval)    guard batched)  RRF fusion)
```

Every stage runs inside a harness that records timings, applies timeouts and falls back instead of raising. The trace from each request feeds the latency report, so the P50/P70/P100 numbers come from the same code path the demo uses.

## Layout

- `src/vaani/harness.py` staged pipeline core: timeouts, fallbacks, retries, tracing
- `src/vaani/embed.py` multilingual-e5-small wrapper, prefixes handled internally
- `src/vaani/indexes.py` usearch HNSW + bm25s primitives
- `src/vaani/strategies.py` query-time strategies over those primitives
- `src/vaani/retriever.py` reciprocal rank fusion across strategies
- `src/vaani/pipeline_text.py` assembles the text-query pipeline
- `src/vaani/answer_extractive.py` model-free answer floor, sub-10ms
- `src/vaani/guards.py` input and groundedness gates (stubs today, models next)
- `scripts/` corpus build, subset cut, index build, eval runner

## Quickstart

Needs Python 3.12 and uv. First run downloads the e5 model (~450MB).

```
uv sync
uv run python scripts/build_corpus.py --lang hin --split val
uv run python scripts/make_subset.py
uv run python scripts/build_indexes.py --corpus data/subset/hin_val_100k --out indexes/hin_val_100k --strategy passage
uv run python scripts/build_indexes.py --corpus data/subset/hin_val_100k --out indexes/hin_val_100k --strategy sentence
uv run python -m vaani.ask "who wrote silent spring"
uv run python scripts/run_eval.py --n 500
```

Tests: `uv run pytest`.

## Dataset

MSMARCO-XI is MS MARCO QnA machine-translated into 14 Indic languages by AI4Bharat (arXiv 2506.01615). Each row keeps the English and translated passages side by side, with human relevance flags and reference answers. The Hindi validation slice used here has 97,941 queries and 950,721 unique passages; roughly 45% of queries have no relevant passage, and those double as ground truth for the abstention guardrail.

## Status

Working today: corpus and subset builders, passage plus sentence indexes with BM25, fused retrieval, harness, extractive answers, abstention gate, eval runner.

Coming next: Sarvam realtime STT with speculative retrieval, vLLM generation on the GPU cluster, Prompt-Guard input checks, HHEM groundedness scoring, more index strategies (fixed-window, semantic-merge, metadata-aware), the web UI and the live deployment.
