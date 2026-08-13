"""Staged pipeline harness: typed results, timeouts, fallbacks, tracing.

A Stage wraps one unit of query-time work. It receives the shared context
dict and returns either a dict delta (merged into the context), or a
Refusal (which stops the pipeline cleanly). Stages never raise to the
caller: errors retry if configured, then fall back, then refuse.

Timeouts run stage functions on a shared thread pool. Python threads
cannot be killed, so a timed-out stage may finish in the background and
its result is discarded. Stage functions must therefore be safe to
abandon (pure reads plus local compute, no half-written state).
"""

from __future__ import annotations

import time
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from typing import Any, Callable, Literal

from pydantic import BaseModel, Field

Ctx = dict[str, Any]
StageFn = Callable[[Ctx], "dict[str, Any] | Refusal"]

_pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="vaani-stage")


class AnswerPayload(BaseModel):
    text: str
    passage_ids: list[str] = Field(default_factory=list)
    kind: Literal["extractive", "generative"] = "extractive"
    language: str | None = None


class Refusal(BaseModel):
    reason_code: str
    message: str = ""


class StageEvent(BaseModel):
    stage: str
    started_ns: int
    dur_ms: float
    outcome: Literal["ok", "timeout", "error", "fallback", "refusal"]
    detail: str = ""


class PipelineResult(BaseModel):
    request_id: str
    answer: AnswerPayload | Refusal
    trace: list[StageEvent]
    total_ms: float


class Stage:
    def __init__(
        self,
        name: str,
        fn: StageFn,
        timeout_ms: float | None = None,
        fallback: "Stage | None" = None,
        retries: int = 0,
    ):
        self.name = name
        self.fn = fn
        self.timeout_ms = timeout_ms
        self.fallback = fallback
        self.retries = retries

    def _call_once(self, ctx: Ctx) -> "dict[str, Any] | Refusal":
        if self.timeout_ms is None:
            return self.fn(ctx)
        future = _pool.submit(self.fn, ctx)
        try:
            return future.result(timeout=self.timeout_ms / 1000.0)
        except FutureTimeout:
            future.cancel()
            raise


class Pipeline:
    def __init__(self, stages: list[Stage]):
        self.stages = stages

    def run(self, request: Ctx) -> PipelineResult:
        # the request dict IS the run context: stage outputs accumulate in
        # it, so a caller that keeps a reference can inspect intermediate
        # artifacts (retrieval ranking etc.) after the run
        t0 = time.perf_counter_ns()
        ctx: Ctx = request
        trace: list[StageEvent] = []
        answer: AnswerPayload | Refusal | None = None

        for stage in self.stages:
            started = time.perf_counter_ns()
            outcome: str = "ok"
            detail = ""
            result: dict[str, Any] | Refusal | None = None

            attempts = stage.retries + 1
            for attempt in range(attempts):
                try:
                    result = stage._call_once(ctx)
                    outcome = "ok"
                    detail = f"ok after {attempt} retries" if attempt else ""
                    break
                except FutureTimeout:
                    outcome, detail = "timeout", f"timeout>{stage.timeout_ms}ms"
                    break  # a timeout already burned the budget, never retry
                except Exception as exc:  # noqa: BLE001 stages must not raise upward
                    outcome = "error"
                    detail = f"{type(exc).__name__}: {exc}"
                    if attempt < attempts - 1:
                        continue

            if outcome in ("timeout", "error") and stage.fallback is not None:
                try:
                    result = stage.fallback.fn(ctx)
                    outcome, detail = "fallback", f"{outcome}: {detail}" if detail else outcome
                except Exception as exc:  # noqa: BLE001
                    result = None
                    outcome, detail = "error", f"fallback failed: {exc}"

            dur_ms = (time.perf_counter_ns() - started) / 1e6

            if isinstance(result, Refusal):
                trace.append(StageEvent(
                    stage=stage.name, started_ns=started, dur_ms=dur_ms,
                    outcome="refusal", detail=result.reason_code,
                ))
                answer = result
                break

            if result is None:
                trace.append(StageEvent(
                    stage=stage.name, started_ns=started, dur_ms=dur_ms,
                    outcome=outcome, detail=detail,
                ))
                answer = Refusal(
                    reason_code=f"stage_{outcome}:{stage.name}", message=detail
                )
                break

            ctx.update(result)
            trace.append(StageEvent(
                stage=stage.name, started_ns=started, dur_ms=dur_ms,
                outcome=outcome, detail=detail,
            ))

        if answer is None:
            found = ctx.get("answer")
            if isinstance(found, (AnswerPayload, Refusal)):
                answer = found
            else:
                answer = Refusal(reason_code="no_answer_produced")

        total_ms = (time.perf_counter_ns() - t0) / 1e6
        return PipelineResult(
            request_id=str(uuid.uuid4()),
            answer=answer,
            trace=trace,
            total_ms=total_ms,
        )
