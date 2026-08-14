# Generation optimization plan

Generation is ~60% of pipeline time (82ms of 133ms P50 on cluster). Four changes, all composable, then re-measure on both machines and pick the demo config from data.

## Changes

1. Shorter answers (both machines, do first)
   - `answer_generative.py`: system prompt gains "in under 20 words", `max_tokens` 48 -> 32.
   - Expected: generation roughly halves. Verify quality on 20 sampled answers by eye.

2. Streaming tokens (both, UX only)
   - `GenerationClient.chat` gains `stream=True` variant; WS route forwards token deltas as `{type: "token"}` events; UI types them out.
   - Does not change benchmark numbers, changes perceived speed.

3. N-gram speculative decoding (cluster)
   - `slurm/vllm_serve.slurm`: add `--speculative-config '{"method":"ngram","num_speculative_tokens":8,"prompt_lookup_max":4}'` (check exact flag syntax against installed vLLM version first).
   - RAG answers copy context spans, the best case for prompt lookup. Expected 1.5-3x decode.

4. Q4 quant on laptop
   - Download `Qwen3-0.6B-Q4_K_M.gguf` next to the Q8 one.
   - `llama-server -m models/<gguf> -ngl 99 -fa 1 --port 8001`; A/B Q8 vs Q4 on speed and answer quality.

## Measurement protocol

- `scripts/gen_bench.py` against each config, 10 runs, report p50.
- Then full `scripts/run_eval.py --n 1000` with generation + guards on the winner per machine.
- Record laptop numbers beside cluster numbers in the report; label hardware for each.

## Laptop bring-up (fallback + live link)

Already done: full indexes local (3.9GB), Q8 GGUF, llama.cpp CUDA build in `tools/llama/`.
Remaining: guard-env equivalent locally (uv venv, transformers 4.49), boot warmup call in `Runtime.__init__` (one full pipeline pass) to clamp P100, cloudflared quick tunnel for the public URL.

## Demo day runbook (cluster, tomorrow evening)

1. `sbatch --export=ALL,VAANI_LLM=Qwen/Qwen3-0.6B slurm/vllm_serve.slurm` (with ngram flag).
2. App on login node: `VAANI_CORPUS=data/corpus/hin_val VAANI_INDEXES=indexes/hin_val VAANI_GENERATION_URL=$(cat vllm_host.txt) VAANI_GUARD_URL=$(cat guard_host.txt) uvicorn ...`
3. One real Sarvam WS session check (about 1 rupee), fix payload field names if they differ.
4. Record demo video with mic, live waterfall, refusal case, Hindi query.
5. Final benchmark run, pull reports, `scancel` everything before leaving.

## Still open after this

Sentence index underperformed (measured); keep passage+bm25 as default. Report writing, submission form, live link decision (laptop vs video only), #RAGInGoa posts (human), Confirm Participation (human).
