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

import time
from pathlib import Path

from fastapi import FastAPI, File, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from vaani.harness import PipelineResult, Refusal

WEB_DIR = Path(__file__).resolve().parents[2] / "web"


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


def create_app(run_pipeline, stt) -> FastAPI:
    """run_pipeline: callable(query: str) -> PipelineResult. stt: has
    transcribe_bytes(audio, filename=..., language=...) -> TranscriptResult."""
    app = FastAPI(title="vaani")

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.post("/api/ask")
    def ask(body: AskRequest):
        result = run_pipeline(body.query)
        return JSONResponse(_result_json(result))

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
        result = run_pipeline(transcript.text)
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

    runtime = Runtime(PipelineConfig(
        corpus_dir=os.environ.get("VAANI_CORPUS", "data/subset/hin_val_100k"),
        index_root=os.environ.get("VAANI_INDEXES", "indexes/hin_val_100k"),
        generation_url=os.environ.get("VAANI_GENERATION_URL") or None,
        device=os.environ.get("VAANI_DEVICE") or None,
    ))
    pipeline = build_text_pipeline(runtime)
    stt = SarvamSTT()
    return create_app(lambda q: pipeline.run({"query": q}), stt)
