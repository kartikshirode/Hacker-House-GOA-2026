"""FastAPI app: text ask, voice ask, health, static demo UI.

The app factory takes its dependencies (pipeline runner + stt) so tests
inject fakes. create_default_app() wires the real runtime once at
startup and serves web/ at the root.

Voice path today: browser records a clip, posts it, Sarvam REST
transcribes (cache + mock honored), the text pipeline answers. The
streaming websocket path with speculative retrieval replaces this in
phase B; response shape stays the same.
"""

from __future__ import annotations

import asyncio
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI, File, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from vaani.harness import PipelineResult, Refusal
from vaani.stt import BudgetExceeded

WEB_DIR = Path(__file__).resolve().parents[2] / "web"

SPECULATE_MIN_CHARS = 6


def _norm_transcript(text: str) -> str:
    """Sarvam finals often differ from the last partial only in case or
    trailing punctuation; matching on this keeps the speculative work."""
    return text.strip().lower().rstrip("?!.,।")


class AskRequest(BaseModel):
    query: str


def _guard_json(ctx: dict) -> dict:
    """Expose guard verdicts, including checked=False fail-open paths,
    so an unchecked answer is never presented as a graded one."""
    out = {}
    for key in ("guard_input", "guard_output"):
        verdict = ctx.get(key)
        if verdict is not None:
            out[key.removeprefix("guard_")] = verdict.model_dump()
    return out


def _retrieval_json(ctx: dict) -> dict:
    """The retrieval signal and the gate it was measured against. Both
    branches report it: seeing 0.849 against a 0.85 gate is what makes a
    refusal legible instead of arbitrary."""
    r = ctx.get("retrieval")
    if r is None:
        return {}
    return {
        "confidence": round(ctx.get("retrieval_signal", r.confidence), 4),
        "threshold": ctx.get("abstain_threshold"),
        "n_hits": len(r.hits),
        "strategy_top_scores": {k: round(v, 4) for k, v in r.strategy_top_scores.items()},
    }


def _result_json(result: PipelineResult, extra_stages: list[dict] | None = None,
                 guards: dict | None = None, retrieval: dict | None = None) -> dict:
    refused = isinstance(result.answer, Refusal)
    stages = [
        {"stage": e.stage, "ms": round(e.dur_ms, 2), "outcome": e.outcome, "detail": e.detail}
        for e in result.trace
    ]
    if extra_stages:
        stages = extra_stages + stages
    return {
        "refused": refused,
        "answer": None if refused else result.answer.model_dump(),
        "refusal": result.answer.model_dump() if refused else None,
        "trace": stages,
        "guards": guards or {},
        "retrieval": retrieval or {},
        "pipeline_ms": round(result.total_ms, 2),
        "total_ms": round(result.total_ms + sum(s["ms"] for s in (extra_stages or [])), 2),
        "request_id": result.request_id,
    }


def create_app(run_pipeline, stt, speculate=None, stt_session_factory=None,
               corpus=None) -> FastAPI:
    """run_pipeline: callable(ctx: dict) -> PipelineResult, where ctx holds
    at least {"query"} and may carry speculative {"query_vec", "retrieval"}.
    stt: transcribe_bytes(audio, ...) -> TranscriptResult for the clip path.
    speculate: callable(text) -> ctx delta, used on streaming partials.
    stt_session_factory: () -> async context manager with send_audio/events,
    enables the realtime websocket route."""
    app = FastAPI(title="vaani")
    # static facts the UI prints in its status strip; reading them from the
    # running app means the page cannot claim a corpus it is not serving
    corpus_stats = dict(corpus or {})

    # The UI is served two ways: from this app (same origin, nothing to
    # configure) and from a static host with the API on another origin.
    # Only the second needs CORS, so it stays opt-in: an unset
    # VAANI_ALLOW_ORIGINS leaves the app exactly as it was.
    origins = [o.strip() for o in os.environ.get("VAANI_ALLOW_ORIGINS", "").split(",") if o.strip()]
    origin_regex = os.environ.get("VAANI_ALLOW_ORIGIN_REGEX") or None
    if origins or origin_regex:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_origin_regex=origin_regex,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["*"],
        )
    # speculation gets one dedicated worker: stale jobs queue here instead
    # of competing with the pipeline for the default executor, and a
    # queued-not-started job cancels cleanly when a newer partial lands
    spec_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="spec")

    @app.get("/healthz")
    def healthz():
        # A mocked STT answers /api/voice with the literal string "mock
        # transcript", which retrieves and answers confidently on nonsense.
        # Advertise the real capability so the UI can refuse the mic
        # instead of presenting that as a transcription.
        left = stt.budget_left() if hasattr(stt, "budget_left") else float("inf")
        return {
            "ok": True,
            "corpus": corpus_stats,
            # a spent budget is as good as no voice for the caller, so the
            # mic greys out on the same flag rather than failing on tap
            "voice": not getattr(stt, "mock", False) and left > 0,
            "streaming": stt_session_factory is not None,
            "stt_budget_left": None if left == float("inf") else left,
        }

    @app.post("/api/ask")
    def ask(body: AskRequest):
        ctx = {"query": body.query}
        result = run_pipeline(ctx)
        return JSONResponse(_result_json(result, guards=_guard_json(ctx),
                                     retrieval=_retrieval_json(ctx)))

    @app.websocket("/ws/voice")
    async def ws_voice(ws: WebSocket):
        await ws.accept()
        if stt_session_factory is None:
            await ws.send_json({"type": "error", "message": "realtime stt not configured"})
            await ws.close()
            return

        loop = asyncio.get_event_loop()
        session = stt_session_factory()
        # one slot, newest partial only: partials arrive faster than they
        # differ, and only the last one can match the final transcript
        spec_norm: str | None = None
        spec_future = None

        async def pump_audio():
            try:
                while True:
                    frame = await ws.receive_bytes()
                    await session.send_audio(frame)
            except (WebSocketDisconnect, RuntimeError):
                pass

        # The upstream realtime session can die on its own: protocol
        # drift, a rejected key, a dropped socket. If that escapes here
        # the ASGI app 500s and the browser sees a socket that opened
        # and went quiet, which looks exactly like a dead mic button.
        # Tell the client instead so it falls back to the clip path.
        try:
            async with session:
                audio_task = asyncio.create_task(pump_audio())
                try:
                    async for event in session.events():
                        if event.kind == "partial" and event.text:
                            await ws.send_json({"type": "partial", "text": event.text})
                            norm = _norm_transcript(event.text)
                            if (speculate is not None
                                    and len(event.text) >= SPECULATE_MIN_CHARS
                                    and norm != spec_norm):
                                if spec_future is not None:
                                    spec_future.cancel()  # no-op once running
                                spec_norm = norm
                                spec_future = spec_pool.submit(speculate, event.text)
                        elif event.kind == "final" and event.text:
                            t_final = time.perf_counter()
                            await ws.send_json({"type": "transcript", "text": event.text})
                            ctx = {"query": event.text}
                            if (spec_future is not None
                                    and spec_norm == _norm_transcript(event.text)):
                                try:
                                    # short bounded wait; either way the cost is
                                    # visible in transcript_to_result_ms below
                                    ctx.update(await asyncio.wait_for(
                                        asyncio.wrap_future(spec_future), timeout=0.05))
                                    ctx["speculative"] = True
                                except Exception:  # noqa: BLE001 fresh retrieval instead
                                    pass
                            spec_norm, spec_future = None, None

                            # generation streams deltas from a worker thread;
                            # forward them until the pipeline returns, then the
                            # result event below is the authoritative answer
                            live = {"on": True}
                            token_sends: list = []

                            def on_token(delta: str, _live=live, _sends=token_sends):
                                if _live["on"]:
                                    _sends.append(asyncio.run_coroutine_threadsafe(
                                        ws.send_json({"type": "token", "text": delta}), loop
                                    ))

                            ctx["on_token"] = on_token
                            result = await loop.run_in_executor(None, run_pipeline, ctx)
                            live["on"] = False
                            # drain pending token sends so none lands after the
                            # authoritative result event
                            for send in token_sends:
                                try:
                                    await asyncio.wrap_future(send)
                                except Exception:  # noqa: BLE001
                                    pass
                            payload = _result_json(result, guards=_guard_json(ctx),
                                         retrieval=_retrieval_json(ctx))
                            payload["type"] = "result"
                            payload["transcript"] = event.text
                            payload["speculative"] = ctx.get("speculative", False)
                            # honest wall clock from final transcript to result,
                            # including any speculative wait, not just stage time
                            payload["transcript_to_result_ms"] = round(
                                (time.perf_counter() - t_final) * 1000, 2)
                            await ws.send_json(payload)
                        elif event.kind == "error":
                            await ws.send_json({"type": "error", "message": event.raw_type})
                except (WebSocketDisconnect, RuntimeError):
                    pass
                finally:
                    audio_task.cancel()
        except Exception as exc:  # noqa: BLE001
            try:
                await ws.send_json({
                    "type": "error",
                    "message": f"realtime stt unavailable: {type(exc).__name__}",
                })
                await ws.close()
            except Exception:  # noqa: BLE001
                pass

    @app.post("/api/voice")
    async def voice(file: UploadFile = File(...), language: str = "unknown"):
        audio = await file.read()
        loop = asyncio.get_event_loop()
        t0 = time.perf_counter()
        # both calls block; keep them off the event loop so ws partials
        # and other requests stay live while this one thinks
        try:
            transcript = await loop.run_in_executor(None, lambda: stt.transcribe_bytes(
                audio, filename=file.filename or "clip.webm", language=language
            ))
        except BudgetExceeded as exc:
            # refusing on purpose, so it reads as a refusal and not a 500
            return JSONResponse({
                "refused": True,
                "answer": None,
                "refusal": {"reason_code": "stt_budget", "message": str(exc)},
                "transcript": "",
                "trace": [{"stage": "stt", "ms": 0.0, "outcome": "refused",
                           "detail": "budget"}],
                "pipeline_ms": 0.0,
                "total_ms": 0.0,
                "request_id": "",
            }, status_code=200)
        stt_ms = (time.perf_counter() - t0) * 1000
        stt_stage = {
            "stage": "stt",
            "ms": round(stt_ms, 2),
            "outcome": "ok" if transcript.text else "empty",
            "detail": ("cached" if transcript.cached else "") + ("mock" if transcript.mock else ""),
        }
        if not transcript.text:
            return JSONResponse({
                "refused": True,
                "answer": None,
                "refusal": {"reason_code": "empty_transcript",
                            "message": "could not hear a question"},
                "transcript": "",
                "trace": [stt_stage],
                "pipeline_ms": 0.0,
                "total_ms": round(stt_ms, 2),
                "request_id": "",
            })
        ctx = {"query": transcript.text}
        result = await loop.run_in_executor(None, run_pipeline, ctx)
        payload = _result_json(result, extra_stages=[stt_stage],
                               guards=_guard_json(ctx), retrieval=_retrieval_json(ctx))
        payload["transcript"] = transcript.text
        payload["language_code"] = transcript.language_code
        return JSONResponse(payload)

    if WEB_DIR.exists():
        app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
    return app


def create_default_app() -> FastAPI:
    from vaani.pipeline_text import PipelineConfig, Runtime, build_text_pipeline
    from vaani.stt import SarvamSTT
    from vaani.stt_realtime import RealtimeSTT

    runtime = Runtime(PipelineConfig(
        corpus_dir=os.environ.get("VAANI_CORPUS", "data/subset/hin_val_100k"),
        index_root=os.environ.get("VAANI_INDEXES", "indexes/hin_val_100k"),
        generation_url=os.environ.get("VAANI_GENERATION_URL") or None,
        guard_url=os.environ.get("VAANI_GUARD_URL") or None,
        device=os.environ.get("VAANI_DEVICE") or None,
        embed_timeout_ms=float(os.environ.get("VAANI_EMBED_TIMEOUT_MS") or 50),
        retrieve_timeout_ms=float(os.environ.get("VAANI_RETRIEVE_TIMEOUT_MS") or 100),
    ))
    pipeline = build_text_pipeline(runtime)
    stt = SarvamSTT()

    session_factory = None
    # VAANI_STT_REALTIME=0 turns the streaming path off and leaves the REST
    # clip path serving voice. The clip path is the verified one; realtime
    # should only be on when a real session has been confirmed end to end,
    # because a half-working socket is worse than no socket: the client
    # stays on it instead of falling back.
    if (os.environ.get("SARVAM_API_KEY")
            and os.environ.get("VAANI_STT_MOCK") != "1"
            and os.environ.get("VAANI_STT_REALTIME", "1") != "0"):
        session_factory = lambda: RealtimeSTT()  # noqa: E731

    return create_app(
        lambda ctx: pipeline.run(ctx),
        stt,
        speculate=runtime.speculative_retrieve,
        stt_session_factory=session_factory,
        corpus={
            "passages": len(runtime.store),
            "strategies": sorted(runtime.retriever.strategies),
            "abstain_threshold": runtime.cfg.abstain_threshold,
            "generation": runtime.genclient is not None,
            "guards": bool(runtime.cfg.guard_url),
        },
    )
