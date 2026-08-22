# Vaani handoff

Written Aug 14, 2026 evening. Deadline is Aug 22, 11:59 PM IST. Cluster access ends tomorrow, Aug 15. This file is the one place to start; everything else links from here.

## What this is

HH Goa 2026 Task 2: a voice RAG over `ai4bharat/MSMARCO-XI`. You speak in Hindi or English, Sarvam transcribes, we retrieve from 950K passages and a small model answers, all under 200ms after the transcript. The task PDF sits at `Task 2/task 2_ hhg.pdf` in the repo root. Read [README.md](README.md) first, it carries the measured state. Design thinking is in [docs/design.md](docs/design.md).

Repo: github.com/kartikshirode/Hacker-House-GOA-2026, public, `main` is the truth. Project lives under `Task 2/vaani`.

## Where we are

Engineering is done and measured. Submission artifacts are not. That's the whole picture.

The 6 technical requirements all have committed evidence: Sarvam STT (REST path verified live), 3 chunking strategies with a head to head ablation, hybrid retrieval, generation on Qwen3-0.6B, a harness with timeouts and fallbacks, and 4 guard layers that refuse on purpose. Latest full run (1000 real queries, full corpus, generation and guards on, cluster GPU):

| | P50 | P70 | P90 | P100 |
|---|---|---|---|---|
| English | 117.2ms | 135.2ms | 166.7ms | 543.2ms |
| Hindi | 98.2ms | 145.6ms | 184.4ms | 554.9ms |

MRR@10 0.4066, recall@10 0.7417, token F1 0.214 over all answerable queries (0.268 on generative ones). P100 is 1 embed hiccup per 1000; we show it, we don't trim it. Ngram speculative decoding took English generation from 84.7ms to 43.5ms with identical outputs. On the laptop (RTX 4060, llama.cpp) the Q8 model generates in 77ms. All reports are in `reports/cluster` and `reports/laptop`.

62 tests pass with `uv run pytest`.

## What's not done, and who should do it

Submission side, in order of risk:

1. Live working link. Biggest open item. The plan is [docs/superpowers/plans/2026-08-14-live-link.md](docs/superpowers/plans/2026-08-14-live-link.md), reworked after a Codex review that's saved verbatim at [docs/reviews/2026-08-14-codex-live-link-review.md](docs/reviews/2026-08-14-codex-live-link-review.md). Short version: submit a permanent Cloudflare Pages URL with a Worker in front that gates abuse and routes to whichever backend is alive. Behind it, either a paid HF Space (about 950 rupees, always on) or the laptop over Tailscale Funnel (free, goes down when the laptop does). Kartik owns the money call; a teammate can start the Pages plus Worker work today since it's the same either way.
2. Video 2, the demo. Planned for tomorrow evening on the cluster while we still have the GPU. Runbook is at the bottom of [docs/superpowers/plans/2026-08-14-generation-optimization.md](docs/superpowers/plans/2026-08-14-generation-optimization.md). Needs Kartik, the cluster login is his.
3. Video 1. 90 seconds, team and process, explicitly not the product. Easy to forget, mandatory. Somebody needs to shoot footage of us actually working.
4. The form at forms.gle/MNvCjcv23Hn2Eeu58. No resubmissions, so it goes in last, after every gate in the live link plan passes.
5. Promotion. Both videos on Instagram, X and LinkedIn, posted by every team member separately, every post carrying #RAGInGoa, and at least 1 Instagram account public. Also the Confirm Participation button on the HHGoa site if nobody has clicked it yet.

Code side, smaller:

- Branch `wip/budget-caps` holds half built spend controls: a ledger ceiling in `stt.py`, upload and utterance caps plus an access token gate in `server.py`, env overrides for generation and guard timeouts so a CPU host doesn't strangle itself at 150ms. It was parked mid-edit when we switched to planning. Tests for it are partly written. Finish it once the hosting track is picked.
- One real Sarvam realtime session (a few rupees) to check the current websocket protocol. Our client targets `/speech-to-text-realtime/ws` with `saaras:v3-realtime`; current docs describe `/speech-to-text/ws` with `saaras:v3` and final transcripts per utterance, and partials may not exist at all. Both are env overridable (`VAANI_STT_WS_URL`, `VAANI_STT_WS_MODEL`, on the wip branch). This decides whether speculative retrieval survives on the public link. The REST clip path (`/api/voice`) is verified and doesn't depend on any of this.
- Deferred on purpose, listed in the optimization plan: ONNX or int8 embedding (embed is 35ms, the biggest fixed cost left) and a partial transcript replay for eval.

## Running it

Needs Python 3.12 and uv. The README Quickstart has the build commands. For the demo stack on a laptop with a GPU:

```
tools\llama\llama-server.exe -m models\Qwen3-0.6B-Q8_0.gguf -ngl 99 -fa 1 -c 2048 --port 8001 --no-webui
set VAANI_CORPUS=data/corpus/hin_val
set VAANI_INDEXES=indexes/hin_val
set VAANI_GENERATION_URL=http://127.0.0.1:8001/v1
uv run uvicorn vaani.server:create_default_app --factory --port 8000
```

Guards need a second venv with transformers pinned to 4.49 (HHEM's remote code breaks on 5.x) serving `vaani.guard_service:app` on port 8002, then `VAANI_GUARD_URL=http://127.0.0.1:8002`. Without it the guards run as stubs and say so in every response. Set `VAANI_STT_MOCK=1` while developing so nothing hits Sarvam.

## Things that aren't in git

Data, indexes and models are gitignored. They exist in 2 places right now:

- Kartik's laptop, under `Task 2/vaani`: `data/corpus/hin_val` (346MB), `indexes/hin_val/passage` with its bm25 folder (about 1.1GB), `models/Qwen3-0.6B-Q8_0.gguf` (610MB) and `Qwen3-0.6B-Q4_K_M.gguf` (378MB), `tools/llama` (the llama.cpp CUDA build). There's also a `sentence` index folder that usearch on Windows can't open; it's the losing strategy anyway and the loader skips it.
- The cluster, `~/vaani` on baramati, same files plus the envs. Unreachable after Aug 15.

Everything is rebuildable from `scripts/` if both copies vanish: corpus from HF, indexes in about an hour on a GPU, GGUFs from Qwen and unsloth on HF. Guard models download from public HF repos on first use.

## Secrets and money

- The Sarvam key lives in `Task 2/vaani/.env`, gitignored, never paste it anywhere. Balance is 100 rupees and we've spent about 1 paisa so far. Every real call lands in `data/stt_usage.jsonl`. A public link with no controls could burn the whole balance in roughly 10 minutes, which is why the spend caps exist and the live link plan leads with them.
- Cluster credentials stay with Kartik. They're not in the repo and shouldn't be sent to anyone.
- The dataset inherits MS MARCO's non commercial research terms. Don't redistribute the corpus, don't expose a download endpoint, keep attribution in the app.

## Honest gaps

The Hindi text path is weaker than English by design: cross lingual retrieval lands at MRR 0.19, and both guard models only read English so they step aside for Devanagari and mark the answer unchecked. The voice path avoids this by translating at STT, which is exactly what the Sarvam session check needs to confirm. 19 English and 75 Hindi answers hit the token cap in the last run and fell back to extractive; the 64 token Hindi cap is still tight. None of this is hidden, the reports itemize it.

## Things that bit us, so they don't bite you

- Windows ssh strips quotes. Never send python one liners or heredocs through `ssh`; write a file, `scp` it, run it. Same for PowerShell inline python, write a script instead.
- Git on Windows turned the slurm scripts CRLF once and sbatch refused them. `.gitattributes` forces LF now; after any ship to the cluster run `sed -i "s/\r$//"` on `slurm/*.slurm` and `scripts/*.py` anyway.
- The cluster venvs are uv venvs, there's no pip inside. Use `.venv/bin/python` directly.
- bm25s needs both `retriever.backend = "numba"` and `activate_numba_scorer()`; one without the other silently runs the slow path (145ms instead of under 1ms).
- `hf download` doesn't write the `.no_exist` markers, so offline loads fail after a seemingly complete download. One online `from_pretrained` fixes it.
- The 2.7GB sentence index restores fine on Linux and fails on Windows with a bare "Invalid argument". Bytes match. It's usearch, not the file.
- Codex as a reviewer has been worth it. 3 rounds so far, every finding triaged into the plan docs with what was accepted and what was deferred and why.

## Timeline from here

Aug 15 cluster day: demo video, final bench, Sarvam session check, and create the HF Space if we go paid. Aug 16 to 17: Pages and Worker live at the permanent URL, spend caps finished. Aug 18 to 19: CPU timeouts tuned where the backend actually runs, then attack our own setup. Aug 20: phone test on mobile data from outside the house. Aug 21: soak. Aug 22: submit hours early, keep everything running until judging confirms. The full day by day with test gates is in the live link plan.
