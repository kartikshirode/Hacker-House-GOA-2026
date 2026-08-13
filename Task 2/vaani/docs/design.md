# Vaani: design notes

Voice-enabled RAG over MSMARCO-XI for the HH Goa 2026 Task 2 submission. You speak a question in an Indian language (or English), the system transcribes it, pulls matching passages out of a vector index and answers from them, with the whole post-transcript path landing under 200ms.

Written Aug 13, updated as decisions land. Facts below were checked against the dataset itself and provider docs on Aug 13; anything marked UNVERIFIED still needs a look.

## The dataset, as it actually is

`ai4bharat/MSMARCO-XI` is MS MARCO QnA machine-translated into 14 Indic languages (IndicRAGSuite, arXiv 2506.01615). Per-language parquet files: ~3.7 GB train, ~460 MB validation. 11.45M rows total, 55.6 GB.

Each row carries more than we expected, and most of it is useful:

- `query` (Indic) and `Eng_Query`
- 10 candidate passages, in English AND the target language, side by side
- `is_selected` flags marking which passages a human judged relevant (can be zero or several)
- `Answer` (Indic) and `Eng_Answer`, human-written
- `query_type`: DESCRIPTION / NUMERIC / ENTITY / PERSON / LOCATION

Hindi validation slice, measured locally after dedup by English text:

- 97,941 queries, 950,721 unique passages, 57,463 qrel pairs
- 44,046 queries (45%) have no selected passage. Their answer text is the literal marker "कोई उत्तर नहीं मिला।". These are gold for testing abstention.
- passage length: avg 317 chars, p50 295, p95 564. Short web extracts.
- the most repeated passages are boilerplate junk (upload errors, weather widgets) that is never marked relevant. Worth a noise filter at index time.
- no-answer rate by type: DESCRIPTION 46.7%, NUMERIC 47.0%, ENTITY 44.1%, PERSON 38.8%, LOCATION 28.0%

So the dataset hands us retrieval ground truth, generation references, abstention gold and a metadata field for routing. We don't need to invent an eval set. The same authors also published IndicMSMarco (1,000 manually translated dev queries) which works as a cleaner, human-quality test set.

Scope call: build on Hindi validation first (950K passages is plenty for a real index), add 1-2 more languages on the cluster if time allows. Train split adds volume, not new structure.

## Latency: reading the requirement honestly

The task says chunking + vector DB retrieval + everything through final output must finish under 200ms. Speech capture itself streams in real time, so the clock that matters starts when the final transcript exists. We'll report P50/P70/P100 for the post-transcript path (that's the stated requirement) and also publish the full voice-to-answer numbers, because hiding them would look evasive.

Two design moves make the budget comfortable instead of heroic:

1. **Speculative retrieval during speech.** Sarvam's realtime STT streams partial transcripts plus VAD events. We fire retrieval on partials while the user is still talking. By the time the final transcript arrives, retrieved context is usually already sitting there (we re-run only if the final text differs materially, and the re-run is cheap anyway). Perceived latency collapses to roughly generation time.
2. **Everything on one box.** STT is a network call by necessity, but embed, search, rerank, generate and guard all run in one process space on one GPU machine. No Pinecone round trips, no hosted LLM. Network RTT from India to a US inference API would eat the budget before the first token showed up.

Millisecond budget for the post-transcript path (targets, to be measured):

| stage | target | notes |
|---|---|---|
| input guard + query embed | 3-8ms | 22M classifier and embed batched together on GPU |
| ANN search x2 + BM25 + fusion | 5-15ms | HNSW over ~1M vectors, in-process |
| rerank top-20 (optional stage) | 10-25ms | ONNX cross-encoder, drops out if budget is tight |
| prompt build | <1ms | template, no LLM |
| generation, ~60 tokens | 60-110ms | Qwen3-class 1.7B/4B on local vLLM, TTFT 20-40ms |
| groundedness check | 10-25ms | HHEM-2.1-Open on GPU, overlapped with token streaming |

P50 lands around 100-160ms with headroom for P100 discipline: every stage has a timeout and a cheaper fallback, and the extractive path (best reranked sentence returned directly) completes in under 10ms when generation is skipped or killed.

## Speech-to-text: Sarvam

Both allowed providers work. Sarvam wins for this dataset:

- Built for exactly these languages. Realtime WS endpoint (`wss://api.sarvam.ai/speech-to-text-realtime/ws`, model `saaras:v3-realtime`) covers all 24 codes including Sanskrit; ElevenLabs Scribe covers our languages except Sanskrit.
- Partial transcripts + VAD events (`transcript.partial`, `vad.speech_end`) are what speculative retrieval needs. A `fast` stream mode exists specifically for low-latency partials.
- REST endpoint has a translate mode (Indic speech in, English text out). That gives us a free second retrieval key, since every passage exists in English too.
- India-hosted API means short RTT from where the demo runs.
- ₹1,000 free signup credits (docs mention ₹100 in one place, UNVERIFIED which is current), credits shared across STT and their chat API.

ElevenLabs Scribe v2 Realtime (~150ms, 90+ languages) is the documented fallback if Sarvam surprises us on quotas.

## Index and retrieval design

Passages are already short, so naive re-chunking would be a fig leaf. The interesting work is granularity, merging, metadata and fusion. Everything expensive happens at index time, where latency is free.

Planned index family (each one is a switchable strategy in the eval):

1. **Passage-level dense index.** The natural unit, the baseline that must be beaten.
2. **Sentence-level small-to-big.** Sentences indexed separately, hits mapped back to parent passages. Fine-grained matching without losing answer context.
3. **Fixed-size token windows with overlap.** 128 tokens, 32 overlap. Exists mostly so the ablation table can show what naive chunking costs.
4. **Semantic-merged parents.** Near-duplicate and same-topic passages clustered (embedding clustering at index time), merged into synthetic parent docs, then split at semantic breakpoints with overlap. Recovers overlap handling on units where it actually means something.
5. **Metadata-aware variants.** Chunks tagged with dominant query_type, appearance counts and a boilerplate-noise score. Query side predicts type (cheap classifier or rules) and biases retrieval. Noise-scored chunks get demoted at index time.
6. **Dual-language index.** English vector space (matched via Sarvam translate output) and Indic vector space (matched via multilingual embedding of the raw transcript). Fused.
7. **Contextual enrichment, budget permitting.** Cluster-level context strings prepended before embedding (Anthropic-style contextual retrieval), generated in bulk on the cluster GPU for high-traffic passages.

Query time stays cheap: 1-2 embeds, 2 ANN lookups + BM25 (bm25s or tantivy), reciprocal rank fusion, optional rerank. Chroma's chunking evaluation backs the direction: semantic/cluster chunkers led recall (0.919 / 0.913 vs ~0.88 fixed-size), and all their cost is index-side.

Embedding model: start with `intfloat/multilingual-e5-small` (118M, 384d) for speed, benchmark `BAAI/bge-m3` and `google/embeddinggemma-300m` on the cluster as quality alternatives. The retrieval eval (MRR@10 against qrels) decides. ONNX/fp16 either way; a single short-query embed must stay under ~8ms.

Vector store: in-process HNSW (faiss or usearch) as primary, because a separate server hop buys nothing at 1M vectors. Qdrant in Docker stays as the "proper vector DB" option to satisfy reviewers who want one visible, and we can ship both behind one interface. UNVERIFIED which reads better for judges; keep the interface neutral.

## Generation

Primary: a small instruct model served by vLLM on the GPU box (Qwen3-1.7B first, 4B if TTFT holds; Sarvam-M via API as a same-vendor hosted fallback). Answers are 1-3 sentences grounded in retrieved passages, cited by passage id. Streaming on, so first token hits the UI fast.

Fallbacks, in order: hosted fast API (Cerebras/Groq free tier, over budget but never wrong to have), then extractive (top reranked sentence, always available, sub-10ms).

MS MARCO answers are short declarative sentences, which is exactly what a 2B-class model does well when the context is good. If quality disappoints, next step is few-shot with dataset answers, not a bigger model.

## Harness

One pipeline object, explicit stages, no raw prompt-in text-out. Each stage declares: input/output types (pydantic), a timeout, a fallback, and a retry policy where retrying makes sense (network stages only). The pipeline emits a structured trace event per stage (start, end, duration, outcome, fallback-used) into a ring buffer that both the latency dashboard and the P50/P70/P100 report read from. LLM output is schema-checked; malformed generations get one repair attempt then fall back to extractive.

Voice session flow: WS from browser → Sarvam realtime WS (partials) → speculative retrieval on stable partials → final transcript → guard + (re)retrieve if drifted → generate → ground-check → answer + trace to UI.

## Guardrails

Know when not to answer, at four gates:

1. **Input safety.** Llama-Prompt-Guard-2-22M (86M multilingual variant if scores need it) for injection/jailbreak, plus a small toxicity/moderation check. Runs batched with query embedding, so it costs almost nothing.
2. **Off-topic gate.** Retrieval confidence thresholds (top score + score mass). MSMARCO-XI is open-domain web QA, so pure off-topic is rare, but "nothing relevant retrieved" is common and the 45% no-answer gold measures exactly this gate.
3. **Abstention.** If retrieval confidence is low or the reranker rejects everything, say "no answer found in the corpus" (in the query's language), mirroring the dataset's own no-answer behavior. Tuned and scored against the 44K no-answer queries.
4. **Groundedness.** HHEM-2.1-Open (110M) scores answer-vs-context entailment. Above threshold: show answer with citations. Below: retract to extractive or abstain, and say why. Runs overlapped with token streaming so it adds one check at the end, not a serial 25ms.

Every refusal is a structured outcome with a reason code, visible in the UI and counted in the eval.

## Evaluation and analytics

- Retrieval: MRR@10 and recall@k against qrels, per chunking strategy and per query_type. This is the ablation table that proves the chunking work.
- Abstention: precision/recall on no-answer gold.
- Groundedness: HHEM score distribution, spot-checked manually.
- Latency: benchmark runner replays a few hundred spoken queries (TTS-generated audio + recorded ones), reports P50/P70/P100 overall and per stage, plus the honest full-voice-path numbers. Live per-request waterfall in the demo UI, because latency is the demo.

## Deployment

Backend (FastAPI + WS) and models on the GPU cluster box, tunneled to a public URL (cloudflared, UNVERIFIED what the cluster allows). Frontend is a small web app (mic capture, live partial transcript, answer with citations, latency waterfall) that can live on Vercel or be served by the backend directly. Live link requirement: the tunneled URL. Local RTX 4060 is for 5-10 minute smoke tests only; index builds and benchmarks run on the cluster.

## Risks

- Sarvam quota/latency surprises → ElevenLabs fallback, recorded-audio demo path as last resort.
- 8 GB local VRAM limits smoke tests → use 100K-passage subset locally, full corpus on cluster.
- Machine-translated Hindi quality → IndicMSMarco human-translated queries as the clean eval slice.
- 200ms P100 with cold caches → warmup pass + timeouts + extractive floor.
- Cluster access details unknown until Aug 14 → everything runs locally at small scale first.
