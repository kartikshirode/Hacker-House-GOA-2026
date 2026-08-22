# Vaani deployment

Live as of Aug 22, 2026. Frontend on Vercel, backend on one GCE VM.

- UI: https://vaani-mu-three.vercel.app
- API: https://34.47.239.128.nip.io (`/healthz`, `/api/ask`, `/api/voice`, `/ws/voice`)

The backend also serves the same UI at its own root, so if Vercel is the
thing that's down the API host is a working fallback.

## Backend

One VM, `vaani-backend`, in GCP project `agentbillboard`, zone
`asia-south1-c` (Mumbai: closest region to the judges).

| | |
|---|---|
| machine | `c4-standard-8` (Intel Xeon Platinum 8581C, Emerald Rapids, 8 vCPU / 30GB) |
| disk | 200GB hyperdisk-balanced (C4 does not take pd-balanced) |
| IP | `34.47.239.128`, reserved as `vaani-backend-ip` so a stop/start keeps it |
| firewall | `vaani-allow-web`, tcp:80,443, target tag `vaani-web` |
| user | `mandar`, key in instance metadata (OS Login off) |

CPU only. The project has `GPUS_ALL_REGIONS = 0`, so no GPU instance can be
created in any region until that quota is raised, and `CPUS-ALL-REGIONS = 12`
caps the machine at 8 vCPU alongside the existing `pumplab-collector`.

That decides two things:

- **Generation is off.** `VAANI_GENERATION_URL` is unset, so the pipeline
  answers extractively. Nothing on a CPU makes `generation_timeout_ms = 150`,
  so wiring a local llama.cpp would just burn the deadline and fall back to
  extractive anyway. Point `VAANI_GENERATION_URL` at any OpenAI-compatible
  endpoint to turn it on.
- **Guards run as stubs.** `VAANI_GUARD_URL` is unset; HHEM and the injection
  classifier both want a GPU. Every response says so in its trace rather than
  presenting an unchecked answer as a graded one.

### Layout on the box

```
/home/mandar/hhgoa/                      the repo, shallow clone of main
/home/mandar/hhgoa/Task 2/vaani/         app root and WorkingDirectory
  .venv/                                 uv sync, torch from the CPU index
  data/corpus/hin_val/                   full corpus, 97,941 q / 950,721 p
  data/subset/hin_val_100k/              5,003 q / 100,000 p  (serving)
  indexes/hin_val_100k/passage/          dense usearch + bm25  (serving)
  indexes/hin_val_full/passage/          full 950K index, built second
/etc/vaani.env                           service env, chmod 600
/etc/systemd/system/vaani.service        uvicorn on 127.0.0.1:8000
/etc/nginx/sites-available/vaani         TLS termination, rate limits
/etc/nginx/conf.d/vaani-zones.conf       limit_req zones + Origin allowlist
```

`pyproject.toml` on the VM has its torch index repointed from
`download.pytorch.org/whl/cu128` to `/whl/cpu`. Without that `uv sync` pulls
the CUDA wheel and several GB of `nvidia-*` libs onto a box with no GPU.

### systemd

`Task 2` has a space in it. Both `WorkingDirectory` and `ExecStart` must be
quoted in the unit or systemd reports `203/EXEC` and restart-loops.

```
sudo systemctl status vaani
sudo journalctl -u vaani -f
sudo systemctl restart vaani     # ~16s boot: warms e5, the store and both indexes
```

### nginx

TLS via certbot on `34.47.239.128.nip.io`, expires 2026-11-20, auto-renewing.
nip.io resolves any `<ip>.nip.io` to that IP, which is what makes a real
Let's Encrypt cert possible without owning a domain.

Rate limits exist because the Sarvam balance is small and the spend caps on
`wip/budget-caps` are unfinished:

| route | limit |
|---|---|
| `/api/ask` | 240 r/min per IP, burst 60 |
| `/api/voice` | 6 r/min per IP, burst 2, 2MB body cap, Origin checked |
| `/ws/voice` | 2 concurrent per IP, Origin checked |

Text asks are deliberately loose: they cost no Sarvam credit and ~8ms of CPU,
and nginx's HTML 429 makes `res.json()` throw in the UI, which renders as
"Server unreachable. Is the backend running?" — a far worse thing for a judge
to see than an extra query.

`map_hash_bucket_size 128` is required; the default 64 cannot hold the Vercel
origin strings and `nginx -t` fails with `could not build map_hash`.

WebSockets do not do CORS, so `/ws/voice` and `/api/voice` get an nginx-level
`Origin` allowlist on top of the app's CORS middleware.

## Frontend

Vercel project `vaani`, deployed from `Task 2/vaani/web`, not git-linked.

`web/index.html` stayed the single source of the UI. `build-config.mjs` copies
it into `public/` at build time and writes `public/config.js` from the
`VAANI_API` env var. Served from the backend, `config.js` sets an empty string
and every call is same-origin exactly as before; served from Vercel it carries
the backend origin. `vercel.json` sets the build command and `no-store` on
`config.js`.

Vercel Authentication was on by default and had to be turned off, otherwise
every visitor hits an SSO login wall. Use only the auto-assigned production
domain `vaani-mu-three.vercel.app`; a manually-set alias is auth-gated.

```
cd "Task 2/vaani/web"
vercel deploy --prod          # redeploy
vercel env ls                 # VAANI_API lives here
```

## Frontend design

Light, monochrome, instrument-panel. Locked to light with `color-scheme:
light` and no `prefers-color-scheme: dark` block, deliberately: the brief
was "it is too black, make it white and black", and honouring the dark
media query would undo that for every viewer whose OS is set to dark.

One radius scale (4px). The mic is the only circle, because it is the only
thing you press to speak. One type system carried over from the old build
so the brand still reads as itself: Tiro Devanagari for the wordmark,
Albert Sans for UI, Spline Sans Mono for every number.

The layout is a split: the answer on the left as text against a rule, no
card, and the telemetry on the right. Judges asked to see the system work,
so the numbers are the second half of the page rather than a footnote.

### What the panel shows, and where it comes from

Nothing on the page is a constant that could drift from the backend.

| Readout | Source |
|---|---|
| passages, retrieval strategies, generation, guards | `/healthz` → `corpus`, built from the loaded `Runtime` |
| voice state and rupees left | `/healthz` → `voice`, `stt_budget_left` |
| retrieval confidence against the gate | `retrieval.confidence` / `retrieval.threshold` |
| per-stage timing and which stages ran | `trace` |
| guard verdicts, including "unchecked" | `guards` |
| hit count, request id | `retrieval.n_hits`, `request_id` |

Two API additions were needed for this and they are worth keeping:
`_retrieval_json()` reports the confidence the abstain decision actually
turned on, and `/healthz` reports the corpus the app has loaded. A refusal
that shows `0.849` against a `0.85` gate is legible; one that just says
"no answer" asks to be trusted.

The resting state draws the gate and lists the stages it will run, so the
panel is informative before the first question instead of three empty
headings.

Motion is feedback only: stage bars scale in on arrival, staggered in
pipeline order, and the answer rises 6px once. Both collapse under
`prefers-reduced-motion`. The only loop is the live voice meter, which is
real data.

Mobile: the split collapses to one column under 900px and the header drops
the three secondary status cells under 620px. Implemented in media queries
and read carefully, but not yet confirmed on a real handset.

## Code changes this deployment needed

All opt-in; local dev with no env set behaves exactly as before.

- `src/vaani/server.py` — CORS middleware behind `VAANI_ALLOW_ORIGINS` /
  `VAANI_ALLOW_ORIGIN_REGEX`, and `/healthz` now reports `voice` and
  `streaming` so the UI can tell whether STT is real.
- `web/index.html` + `web/config.js` — `window.VAANI_API` indirection for
  `fetch` and the WebSocket URL, and the mic disables itself when
  `/healthz` says `voice: false`.

**None of this is pushed.** The changes live in a local clone and on the VM
only; nobody asked for a PR against `kartikshirode/Hacker-House-GOA-2026`.

### The VM's clone has uncommitted edits

`git pull` on that box will clobber or conflict with four files:
`pyproject.toml` (torch index repointed to CPU), `src/vaani/server.py`,
`web/index.html`, `web/config.js`. Stash or re-apply after any pull.

## Measured on this box

60 subset queries through the live pipeline, localhost, generation off:

```
answered 58/60   refused 2
pipeline ms: p50=7.8  p90=9.7  max=11.3
```

In the browser through Vercel and nginx, a cold query is ~16ms end to end:
`embed_query 14.8ms, retrieve 1.4ms, answer 0.2ms`. Embedding is the whole
cost, as the README predicted.

### Capacity, measured 2026-08-22

Concurrency sweep against the running app, 200 requests per level, index
build paused so the numbers are clean:

| concurrency | req/s | p50 | p90 | p99 | stage timeouts |
|---|---|---|---|---|---|
| 1 | 94 | 10.2ms | 11.6ms | 14.3ms | 0 |
| 2 | 96 | 17.9ms | 22.7ms | 224ms | 0 |
| 4 | 73 | 54.2ms | 58.6ms | 65.3ms | 0 |
| 8 | 58 | 137ms | 147ms | 160ms | 0 |
| 16 | 58 | 202ms | 278ms | 286ms | 2 |
| 32 | 58 | 206ms | 272ms | 291ms | 2 |

Throughput plateaus around **58 req/s**; past 8 concurrent the box is
saturated and latency grows linearly. Refusals stay flat at 23 of 200
across every level, which is the genuine abstain rate for that query set.

**This used to fall over at 4 concurrent.** `embed_query` carried a
hardcoded 50ms deadline tuned on the GPU rig where embedding is about 1ms.
On CPU it is 9ms idle and 60-80ms under contention, so at 4+ concurrent
*every* request tripped the stage timeout and refused: 200 of 200. Three
judges opening the link at once would all have seen "no answer".

Fixed by making the CPU-sensitive deadlines configurable:

| env | default | set here |
|---|---|---|
| `VAANI_EMBED_TIMEOUT_MS` | 50 | 600 |
| `VAANI_RETRIEVE_TIMEOUT_MS` | 100 | 400 |
| `OMP_NUM_THREADS` | - | 2 |

`OMP_NUM_THREADS=2` matters as much as the deadlines: 8 torch threads
across 8 concurrent requests oversubscribe 4 physical cores and thrash.

### Retrieval quality on the serving config

`scripts/run_eval.py --n 500`, 100K subset, generation off, guards stubbed.
279 of 500 queries are answerable, 221 have no answer in the corpus.

| | English | Hindi text |
|---|---|---|
| MRR@10 | 0.7200 | 0.3813 |
| recall@10 | 0.9659 | 0.5854 |
| token F1 | 0.2659 | 0.0689 |
| answered | 429 | 116 |
| refused | 71 | 384 |
| abstention precision | 0.7183 | 0.4818 |
| abstention recall | 0.2308 | 0.8371 |
| pipeline p50 | 10.5ms | 13.4ms |
| pipeline p90 | 13.4ms | 16.1ms |

English MRR@10 of 0.72 is well above the README's 0.4066, and that is not
an improvement: the README figure is over the full 950,721-passage corpus
and this is a 100K subset with roughly a tenth of the distractors. It is an
easier retrieval problem. Expect the number to fall back toward the
published one when the full index is switched in.

By query type, English MRR@10: LOCATION 0.806, NUMERIC 0.793, ENTITY 0.740,
DESCRIPTION 0.694, PERSON 0.558.

Abstention recall of 0.23 on English is the honest weak spot: of 221
no-answer queries it only refuses 51. It is tuned to answer rather than to
refuse, and the 20 false refusals out of 279 answerable are the price.

### Known: Hindi text abstains

A Hindi *text* query usually returns `low_confidence`. This is the repo's own
documented gap, not a deployment fault: the dense index is built over English
passage text and cross-lingual retrieval measures MRR 0.19. The intended
Hindi route is voice, where Sarvam translates at STT. The abstain gate firing
here is the guardrail working.

## Voice

Voice is **live**. `SARVAM_API_KEY` sits in `/etc/vaani.env` only (chmod 600,
owned by the service user) and nowhere else. Never put it in git and never in
the Vercel project — that bundle is downloadable by anyone.

`/healthz` reports the real capability:

```
{"ok":true,"voice":true,"streaming":true,"stt_budget_left":24.9917}
```

The UI reads it on load and greys out the mic when `voice` is false, which
covers both "no key" and "budget spent" without the caller tapping into a
failure.

### Spend caps

The ledger recorded spend before but nothing enforced it. `stt.py` now has a
hard ceiling, on by default:

| env | default | effect |
|---|---|---|
| `VAANI_STT_BUDGET_RUPEES` | 25 | past this, `BudgetExceeded`; 0 disables |
| `VAANI_STT_MAX_CLIP_BYTES` | 1,000,000 (400,000 set here) | oversized clips refused before any API call |

Both checks sit **after** the cache lookup, so a replayed clip stays free and
answerable even once the budget is gone. `BudgetExceeded` surfaces as a
`stt_budget` refusal, never a 500 — refusing on purpose is designed
behaviour here.

On top of that, nginx allows 6 `/api/voice` per minute per IP and 2
concurrent `/ws/voice`, and every transcription is cached by audio hash so
the same clip is never paid for twice.

Verified with one real 1-second call: 402ms round trip, ledger recorded
₹0.0083, `stt_budget_left` moved 25.0 → 24.9917. Total spend to date is
under one paisa.

```
cat data/stt_usage.jsonl        # every real call, seconds and rupees
curl -s localhost:8000/healthz  # remaining budget
```

To take voice back down: `sudo sed -i 's/^SARVAM_API_KEY=.*/VAANI_STT_MOCK=1/' /etc/vaani.env && sudo systemctl restart vaani`

### Voice activity detection

Sarvam bills by the audio second, so silence never leaves the browser.
`web/index.html` gates both voice paths:

- **streaming** — an RMS gate on each AudioWorklet frame with hysteresis
  (`VAD_OPEN` 0.012 to open, `VAD_CLOSE` 0.006 to stay open), a 700ms
  hangover and 3 pre-roll frames. The hysteresis stops the gate chattering
  mid-sentence; the pre-roll keeps word onsets a naive gate clips.
- **clip** — the AnalyserNode already driving the voice bars is sampled at
  10Hz during recording. A clip that never crossed `VAD_OPEN` is not
  uploaded at all; it would have cost a call and come back empty anyway.

LiveKit was considered and skipped. It would have replaced the measured
AudioWorklet path with WebRTC on submission day, needs its own cloud
account, and saves no Sarvam credit by itself — the VAD is the part that
actually cuts spend.

### The key is in the Claude transcript

It was pasted into chat to get here. Rotate it in the Sarvam console once
judging is done, and update `/etc/vaani.env`. Nothing else needs changing.

## Index build: what was wrong, and where it runs

Audited 2026-08-22 before rebuilding the full corpus.

**Checked and cleared.** `max_seq_length` is 512 against a longest passage
of 337 tokens, so nothing is silently truncated. `dtype="f16"` in the
usearch index was the obvious suspect and is **not** a problem: measured
against exact float32 cosine on 20K passages, f16 scores recall@10 0.9428
and f32 0.9393, and both flip the 0.85 abstain gate on 0.25% of queries.
The difference is noise. Row-offset alignment between the builder and
`PassageStore` is correct, both sort by `passage_id`.

**The real fault: usearch defaults.** The index was built at connectivity
16 / expansion_add 128 and queried at expansion_search 64, all library
defaults nobody chose. Recall@10 against exact cosine, 20K passages:

| | recall@10 | ms/query |
|---|---|---|
| defaults (what was shipping) | 0.9418 | 0.02 |
| expansion_search 256, query-time only | 0.9840 | 0.07 |
| connectivity 32 + expansion_add 256 + search 256 | 0.9918 | 0.10 |

Retrieval is 1.3ms of a 10ms pipeline, so the defaults were saving
nothing. On the live 500-query eval the query-time change alone moved
**MRR@10 from 0.7200 to 0.7486** and recall@10 from 0.9659 to 0.9713, for
0.46ms of p50. Expect a bigger gain at 950K, since HNSW recall degrades
with corpus size.

`expansion_search` is query-time, so the index already serving picked it
up on restart with no rebuild. `VAANI_EXPANSION_SEARCH` overrides it.
The graph parameters only apply to indexes built from now on.

**Also fixed:** `build_indexes.py` embedded in one silent call that
printed nothing for hours and saved nothing until the end. A Slurm time
limit or a dropped session threw the whole run away, and there was no way
to tell a slow job from a hung one. It now embeds in chunks, prints rate
and ETA, and check-points the vectors so a re-run resumes.

### Where the build runs

The build is GPU work; serving is not. Measured embedding throughput on
this CPU box is **75 passages/s**, so 950,721 passages is about 3.5 hours
of embedding alone, and a full run was tracking toward 4.5 hours.

It belongs on the Baramati cluster (`aicoeserver05`, `gpu:1g.24gb` MIG
slices, the same slice class the README benchmarked on). Estimated 25-45
minutes end to end. Job scripts live at `Desktop/hpc-cluster/`:
`vaani-00-probe.sh` (2 minutes, checks GPU, CPU count and whether the
compute nodes have outbound internet) then `vaani-01-build-index.sh`.

Two cluster traps, both from `hpc-cluster/CONTEXT.md`: `srun` is broken so
everything goes through `sbatch`, and only the `torch-gpu` conda env is
built for sm_120. A third is ours: `--cpus-per-task` defaults to 1, which
would leave HNSW and BM25 construction single-threaded.

**Stage the repo, do not clone it on the cluster.** The recall fix above
is not pushed to GitHub, so a fresh clone builds at the old defaults. The
job script checks for this and refuses to run rather than quietly
producing a worse index.

## Full-corpus switch

`indexes/hin_val_full` is the 950,721-passage index the README benchmarks,
built after the 100K one so a working link existed first. To serve it:

Set these two lines in `/etc/vaani.env` literally — do not sed both at once,
the corpus dir keeps its name and only the index gains `_full`:

```
VAANI_CORPUS=data/corpus/hin_val
VAANI_INDEXES=indexes/hin_val_full
```

Then check the pair matches before restarting. Row offsets are positional
(`ORDER BY passage_id` in both `build_indexes.load_passages` and
`PassageStore.load`), so a mismatched corpus/index pair returns plausible
**wrong** passages with no error at all:

```
jq -r .corpus indexes/hin_val_full/passage/meta.json   # must equal VAANI_CORPUS
sudo systemctl restart vaani
```

After the restart, verify an answer's `passage_id` chip resolves to text that
actually matches the answer. A healthy `/healthz` proves nothing here.

Roll back by pointing the same two vars at the 100K pair. Boot is slower on
the full corpus; keep `TimeoutStartSec` generous.

## Cost

`c4-standard-8` in asia-south1 plus 200GB hyperdisk runs on the order of
$0.40-0.50/hr while up. Stop the VM when it isn't being judged:

```
gcloud compute instances stop vaani-backend --project=agentbillboard --zone=asia-south1-c
```

The reserved IP survives a stop, so the nip.io hostname, the cert and the
Vercel config all still line up on restart. A reserved-but-unattached IP
bills a small hourly rate, which is the price of keeping the URL stable.
