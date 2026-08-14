# Generation optimization plan (v2, post review)

Generation is ~60% of pipeline time (82ms of 133ms P50 on cluster). Four changes, then re-measure on both machines and pick the demo config from data. A Codex review of v1 raised 13 findings; the accepted ones are folded in below.

## Changes

1. Shorter answers (both machines, do first)
   - Prompt gains "in under 20 words"; max_tokens 32 for English.
   - Hindi keeps a 64 cap. Devanagari costs 2-4 tokens per word on the Qwen3 tokenizer, 32 would cut mid-sentence (finding 4).
   - finish_reason is checked now. A length-cut answer raises and the harness serves the extractive fallback instead of a chopped sentence (finding 4).
   - Empty output and unterminated think blocks also raise to the fallback, rather than becoming a fake abstention or a leaked reasoning dump (finding 12).

2. Streaming tokens (both, UX only)
   - chat_stream forwards deltas to a callback; the WS route sends token events; the UI types them out.
   - Deltas are held until the text can no longer be NO_ANSWER or a think tag, so nothing shown ever gets retracted by the abstention path (finding 1).
   - The final result event stays authoritative and replaces streamed text. After the pipeline returns the server drops late tokens; stream lifetime is bounded by the httpx read timeout (finding 2).

3. N-gram speculative decoding (cluster)
   - vllm_serve.slurm defaults to method ngram, num_speculative_tokens 4, prompt_lookup_max 4, prompt_lookup_min 2. Override with VAANI_SPEC, disable with VAANI_SPEC=off (finding 9).
   - vLLM version goes into the job log; gains get measured against a VAANI_SPEC=off baseline, not assumed (finding 9).
   - Host files publish only after /v1/models and the guard /healthz answer, so the app never reads a host file pointing at a server that is still loading (finding 10). Model resolution in the client got its own timeout and retries.

4. Q4 quant on laptop
   - Qwen3-0.6B-Q4_K_M.gguf (unsloth build) sits beside the Q8_0 (Qwen official). Not the same conversion pipeline; the report notes provenance, server flags stay identical between runs (finding 11).
   - llama-server -m models/<gguf> -ngl 99 -fa 1 --port 8001; A/B on speed and answer quality.

## Guard scope fix (finding 5)

HHEM-2.1-Open is English-only. Hindi generative answers now skip the groundedness gate and the trace records hhem_english_only, instead of scoring Hindi text against English passages and refusing on noise. The demo voice path translates to English at STT, so most generative answers still get graded.

## Speculative retrieval fix (finding 8)

The WS route tracks one newest partial instead of a dict of every partial seen. Reuse at final time matches on normalized text (case, trailing punctuation stripped), not exact equality.

## Web client (finding 3)

The browser recorded webm and posted clips while the WS route expected 16kHz PCM16, so nothing actually streamed. index.html gains an AudioWorklet path: mono PCM16 at 16kHz over /ws/voice, live partials, typed tokens, final result replaces everything. The REST clip path stays as fallback when realtime STT is not configured.

## Measurement protocol

- scripts/gen_bench.py takes --generation-url and --guard-url now, times English and Hindi separately and counts truncations (finding 7).
- Then full scripts/run_eval.py --n 1000 on the winner per machine. The report records the served model, refusal reasons, fallback counts, stage outcomes and token F1 against the reference answers (finding 6, scoped).
- Label hardware for each run.

## Boot warmup (finding 13)

One arbitrary pipeline pass could stop at the abstain gate and warm nothing behind it. Runtime now warms each component on purpose: embed, retrieve, one generation call, both guard endpoints.

## Left out on purpose

- Finding 6's full answer-metric suite (TTFT distributions, per-token usage) is cut to token F1 plus outcome counts. Enough to compare configs, cheap to keep.
- Finding 11's matched-quant conversion is skipped; provenance gets noted instead. This is a speed check, not a quant paper.

## Deferred from review round 2

- R2-14, speculative-retrieval replay in eval: would measure the spec hit rate and true transcript-to-result percentiles, but needs recorded partial transcripts. The server now reports transcript_to_result_ms live, which covers the honesty half; the replay harness waits until after submission artifacts are safe.
- R2-16, ONNX or int8 embedding: embed at 34.8ms is now the biggest fixed cost and int8 could roughly halve it, but swapping the encoder demands a full quality rerun to prove MRR holds. Worth doing only if a cluster session remains after the demo video and live link are locked.
- R2-2 is mitigated, not solved: chat_stream now enforces a total deadline so a slow stream cannot hold a worker much past the stage timeout, but true cancellation still needs an async client; the harness docstring keeps the tradeoff documented.

## Laptop bring-up (fallback + live link)

Already done: full indexes local (3.9GB), Q8 and Q4 GGUFs, llama.cpp CUDA build in tools/llama/.
Remaining: guard-env equivalent locally (uv venv, transformers 4.49), cloudflared quick tunnel for the public URL.

## Demo day runbook (cluster, evening)

1. sbatch --export=ALL,VAANI_LLM=Qwen/Qwen3-0.6B slurm/vllm_serve.slurm then wait for vllm_host.txt and guard_host.txt to appear; they publish on readiness now.
2. App on login node: VAANI_CORPUS=data/corpus/hin_val VAANI_INDEXES=indexes/hin_val VAANI_GENERATION_URL=$(cat vllm_host.txt) VAANI_GUARD_URL=$(cat guard_host.txt) uvicorn ...
3. One real Sarvam WS session check (about 1 rupee), fix payload field names if they differ.
4. Record demo video with mic, live waterfall, refusal case, Hindi query.
5. Final benchmark run, pull reports, scancel everything before leaving.

## Still open after this

Sentence index underperformed (measured); passage plus bm25 stays the default. Report writing, submission form, live link decision (laptop vs video only), #RAGInGoa posts (human), Confirm Participation (human).
