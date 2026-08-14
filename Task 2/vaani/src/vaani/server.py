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
import time
from pathlib import Path

from fastapi import FastAPI, File, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from vaani.harness import PipelineResult, Refusal

WEB_DIR = Path(__file__).resolve().parents[2] / "web"

SPECULATE_MIN_CHARS = 6


def _norm_transcript(text: str) -> str:
    """Sarvam finals often differ from the last partial only in case or
    trailing punctuation; matching on this keeps the speculative work."""
    return text.strip().lower().rstrip("?!.,।")


class AskRequest(BaseModel):
    query: str


def _result_json(result: PipelineResult, extra_stages: list[dict] | None = None) -> dict:
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
        "pipeline_ms": round(result.total_ms, 2),
        "total_ms": round(result.total_ms + sum(s["ms"] for s in (extra_stages or [])), 2),
        "request_id": result.request_id,
    }


def create_app(run_pipeline, stt, speculate=None, stt_session_factory=None) -> FastAPI:
    """run_pipeline: callable(ctx: dict) -> PipelineResult, where ctx holds
    at least {"query"} and may carry speculative {"query_vec", "retrieval"}.
    stt: transcribe_bytes(audio, ...) -> TranscriptResult for the clip path.
    speculate: callable(text) -> ctx delta, used on streaming partials.
    stt_session_factory: () -> async context manager with send_audio/events,
    enables the realtime websocket route."""
    app = FastAPI(title="vaani")

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.post("/api/ask")
    def ask(body: AskRequest):
        result = run_pipeline({"query": body.query})
        return JSONResponse(_result_json(result))

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
        spec_future: asyncio.Future | None = None

        async def pump_audio():
            try:
                while True:
                    frame = await ws.receive_bytes()
                    await session.send_audio(frame)
            except (WebSocketDisconnect, RuntimeError):
                pass

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
                            spec_norm = norm
                            spec_future = loop.run_in_executor(
                                None, speculate, event.text
                            )
                    elif event.kind == "final" and event.text:
                        await ws.send_json({"type": "transcript", "text": event.text})
                        ctx = {"query": event.text}
                        if (spec_future is not None
                                and spec_norm == _norm_transcript(event.text)):
                            try:
                                ctx.update(await asyncio.wait_for(spec_future, timeout=0.2))
                                ctx["speculative"] = True
                            except Exception:  # noqa: BLE001 fresh retrieval instead
                                pass
                        spec_norm, spec_future = None, None

                        # generation streams deltas from a worker thread;
                        # forward them until the pipeline returns, then the
                        # result event below is the authoritative answer
                        live = {"on": True}

                        def on_token(delta: str, _live=live):
                            if _live["on"]:
                                asyncio.run_coroutine_threadsafe(
                                    ws.send_json({"type": "token", "text": delta}), loop
                                )

                        ctx["on_token"] = on_token
                        result = await loop.run_in_executor(None, run_pipeline, ctx)
                        live["on"] = False
                        payload = _result_json(result)
                        payload["type"] = "result"
                        payload["transcript"] = event.text
                        payload["speculative"] = ctx.get("speculative", False)
                        await ws.send_json(payload)
                    elif event.kind == "error":
                        await ws.send_json({"type": "error", "message": event.raw_type})
            except (WebSocketDisconnect, RuntimeError):
                pass
            finally:
                audio_task.cancel()

    @app.post("/api/voice")
    async def voice(file: UploadFile = File(...), language: str = "unknown"):
        audio = await file.read()
        t0 = time.perf_counter()
        transcript = stt.transcribe_bytes(
            audio, filename=file.filename or "clip.webm", language=language
        )
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
        result = run_pipeline({"query": transcript.text})
        payload = _result_json(result, extra_stages=[stt_stage])
        payload["transcript"] = transcript.text
        payload["language_code"] = transcript.language_code
        return JSONResponse(payload)

    if WEB_DIR.exists():
        app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
    return app


def create_default_app() -> FastAPI:
    import os

    from vaani.pipeline_text import PipelineConfig, Runtime, build_text_pipeline
    from vaani.stt import SarvamSTT
    from vaani.stt_realtime import RealtimeSTT

    runtime = Runtime(PipelineConfig(
        corpus_dir=os.environ.get("VAANI_CORPUS", "data/subset/hin_val_100k"),
        index_root=os.environ.get("VAANI_INDEXES", "indexes/hin_val_100k"),
        generation_url=os.environ.get("VAANI_GENERATION_URL") or None,
        guard_url=os.environ.get("VAANI_GUARD_URL") or None,
        device=os.environ.get("VAANI_DEVICE") or None,
    ))
    pipeline = build_text_pipeline(runtime)
    stt = SarvamSTT()

    session_factory = None
    if os.environ.get("SARVAM_API_KEY") and os.environ.get("VAANI_STT_MOCK") != "1":
        session_factory = lambda: RealtimeSTT()  # noqa: E731

    return create_app(
        lambda ctx: pipeline.run(ctx),
        stt,
        speculate=runtime.speculative_retrieve,
        stt_session_factory=session_factory,
    )
