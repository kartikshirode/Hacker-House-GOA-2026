"""Sarvam realtime speech-to-text over websocket.

Protocol per docs.sarvam.ai (api-reference/speech-to-text/transcribe/
realtime/ws): endpoint wss://api.sarvam.ai/speech-to-text-realtime/ws,
model saaras:v3-realtime only, mono linear16 audio as base64, server
messages typed session.begin / transcript.partial / transcript.final /
vad.speech_start / vad.speech_end / error.

Exact payload field names are not fully documented, so parsing is
deliberately tolerant: the transcript is looked up under several keys.
Verify against one real session before the demo and tighten if needed.

Partials are what make the demo fast: the caller fires speculative
retrieval on each partial, so context is ready before speech ends.
"""

from __future__ import annotations

import base64
import json
import os
from typing import AsyncIterator, Literal

from pydantic import BaseModel

# The endpoint and model live in envs because Sarvam's canonical docs
# now describe GET /speech-to-text/ws with saaras:v3, while this path
# may be legacy. The paid session check flips these without a code edit.
REALTIME_URL = os.environ.get(
    "VAANI_STT_WS_URL", "wss://api.sarvam.ai/speech-to-text-realtime/ws"
)
MODEL = os.environ.get("VAANI_STT_WS_MODEL", "saaras:v3-realtime")


class SpeechEvent(BaseModel):
    kind: Literal["begin", "partial", "final", "speech_start", "speech_end", "error", "other"]
    text: str = ""
    language_code: str | None = None
    raw_type: str = ""


_KIND_BY_TYPE = {
    "session.begin": "begin",
    "transcript.partial": "partial",
    "transcript.final": "final",
    "vad.speech_start": "speech_start",
    "vad.speech_end": "speech_end",
    "error": "error",
}


def parse_event(message: str | bytes) -> SpeechEvent:
    try:
        data = json.loads(message)
    except (json.JSONDecodeError, TypeError):
        return SpeechEvent(kind="other", raw_type="unparseable")
    if not isinstance(data, dict):
        return SpeechEvent(kind="other", raw_type="unparseable")

    raw_type = str(data.get("type", ""))
    kind = _KIND_BY_TYPE.get(raw_type, "other")

    # transcript location varies; check the plausible spots
    text = ""
    for source in (data, data.get("data") or {}, data.get("payload") or {}):
        if isinstance(source, dict):
            for field in ("transcript", "text"):
                value = source.get(field)
                if isinstance(value, str) and value:
                    text = value
                    break
        if text:
            break

    language = None
    for source in (data, data.get("data") or {}):
        if isinstance(source, dict) and isinstance(source.get("language_code"), str):
            language = source["language_code"]
            break

    return SpeechEvent(kind=kind, text=text, language_code=language, raw_type=raw_type)


def audio_message(pcm16: bytes) -> str:
    """Wrap a mono 16kHz linear16 chunk for transmission."""
    return json.dumps({
        "type": "audio",
        "data": base64.b64encode(pcm16).decode("ascii"),
    })


class RealtimeSTT:
    """Thin session wrapper. Open only while the mic is hot: streaming
    time is billed, so connect late and close early."""

    def __init__(
        self,
        api_key: str | None = None,
        language: str = "auto",
        stream_type: str = "fast",
        mode: str = "translate",
        url: str = REALTIME_URL,
    ):
        self.api_key = api_key if api_key is not None else os.environ.get("SARVAM_API_KEY", "")
        self.language = language
        self.stream_type = stream_type
        # translate mode is load-bearing: it turns hindi speech into
        # english text, which is the path the english-only guards and the
        # english indexes are built for. The paid session check must
        # confirm hindi speech actually comes back as english.
        self.mode = mode
        self.url = url
        self._ws = None

    async def __aenter__(self) -> "RealtimeSTT":
        import websockets

        if not self.api_key:
            raise RuntimeError("SARVAM_API_KEY is not set")
        query = (
            f"?model={MODEL}&language-code={self.language}"
            f"&stream-type={self.stream_type}&mode={self.mode}"
            f"&input-audio-codec=linear16&input-audio-rate=16000"
        )
        self._ws = await websockets.connect(
            self.url + query,
            additional_headers={"api-subscription-key": self.api_key},
        )
        return self

    async def __aexit__(self, *exc) -> None:
        if self._ws is not None:
            await self._ws.close()
            self._ws = None

    async def send_audio(self, pcm16: bytes) -> None:
        await self._ws.send(audio_message(pcm16))

    async def events(self) -> AsyncIterator[SpeechEvent]:
        async for message in self._ws:
            yield parse_event(message)
