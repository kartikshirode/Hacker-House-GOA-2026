"""Assemble the text-query pipeline: guard, embed, retrieve, answer.

Voice arrives in phase B as a stage in front of this pipeline; nothing
downstream changes.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from vaani import answer_extractive, answer_generative, guards
from vaani.answer_generative import GenerationClient
from vaani.embed import DEFAULT_MODEL, Embedder
from vaani.harness import Pipeline, Refusal, Stage
from vaani.retriever import Retriever
from vaani.store import PassageStore
from vaani.strategies import load_strategies


class PipelineConfig(BaseModel):
    corpus_dir: str
    index_root: str
    k: int = 10
    # applied to the best dense cosine across strategies; e5 similarities
    # sit high (roughly 0.75-0.95), so the useful range is narrow
    abstain_threshold: float = 0.85
    strategies: list[str] | None = None
    model: str = DEFAULT_MODEL
    device: str | None = None
    # None disables generation and the extractive path answers directly
    generation_url: str | None = None
    generation_model: str = "Qwen/Qwen3-1.7B"
    generation_timeout_ms: float = 150.0


class Runtime:
    """Loaded-once resources shared across requests."""

    def __init__(self, cfg: PipelineConfig):
        self.cfg = cfg
        self.embedder = Embedder(cfg.model, device=cfg.device)
        self.store = PassageStore.load(Path(cfg.corpus_dir))
        self.retriever = Retriever(load_strategies(Path(cfg.index_root)), self.store)
        self.genclient = None
        if cfg.generation_url:
            self.genclient = GenerationClient(
                base_url=cfg.generation_url,
                model=cfg.generation_model,
                timeout_s=cfg.generation_timeout_ms / 1000.0,
            )
        # first encode pays model warmup; do it here, not on a request
        self.embedder.encode_queries(["warmup"])


def build_text_pipeline(runtime: Runtime) -> Pipeline:
    cfg = runtime.cfg

    def guard_input(ctx):
        verdict = guards.check_input(ctx["query"])
        if not verdict.allowed:
            return Refusal(reason_code="unsafe_input", message=verdict.reason)
        return {"guard_input": verdict}

    def embed_query(ctx):
        vec = runtime.embedder.encode_queries([ctx["query"]])[0]
        return {"query_vec": vec}

    def retrieve(ctx):
        result = runtime.retriever.retrieve(
            ctx["query"], ctx["query_vec"], k=cfg.k, strategies=cfg.strategies
        )
        return {"retrieval": result}

    def abstain_gate(ctx):
        r = ctx["retrieval"]
        dense = [
            v for name, v in r.strategy_top_scores.items() if name.endswith("_dense")
        ]
        signal = max(dense) if dense else r.confidence
        if not r.hits or signal < cfg.abstain_threshold:
            return Refusal(
                reason_code="low_confidence",
                message=f"confidence={signal:.3f} below {cfg.abstain_threshold}",
            )
        return {}

    def extractive(ctx):
        return {"answer": answer_extractive.answer(ctx["retrieval"].hits, ctx["query"])}

    def generative(ctx):
        result = answer_generative.answer(
            runtime.genclient, ctx["retrieval"].hits, ctx["query"]
        )
        if isinstance(result, Refusal):
            return result
        return {"answer": result}

    if runtime.genclient is not None:
        # generation gets a hard deadline; blowing it degrades to the
        # sub-10ms extractive floor instead of blowing the budget
        answer_stage = Stage(
            "answer", generative,
            timeout_ms=cfg.generation_timeout_ms + 25,
            fallback=Stage("extractive", extractive),
        )
    else:
        answer_stage = Stage("answer", extractive, timeout_ms=40)

    def guard_output(ctx):
        payload = ctx["answer"]
        context = [h.eng_text for h in ctx["retrieval"].hits[:3]]
        verdict = guards.check_output(payload.text, context)
        if not verdict.allowed:
            return Refusal(reason_code="ungrounded_answer", message=verdict.reason)
        return {}

    return Pipeline([
        Stage("guard_input", guard_input),
        Stage("embed_query", embed_query, timeout_ms=50),
        Stage("retrieve", retrieve, timeout_ms=60),
        Stage("abstain_gate", abstain_gate),
        answer_stage,
        Stage("guard_output", guard_output, timeout_ms=40),
    ])
