import asyncio
import base64
import json

import pytest

from vaani.stt_realtime import RealtimeSTT, audio_message, parse_event


def test_parse_known_event_types():
    cases = {
        "session.begin": "begin",
        "transcript.partial": "partial",
        "transcript.final": "final",
        "vad.speech_start": "speech_start",
        "vad.speech_end": "speech_end",
        "error": "error",
        "something.new": "other",
    }
    for raw, kind in cases.items():
        event = parse_event(json.dumps({"type": raw}))
        assert event.kind == kind, raw
        assert event.raw_type == raw


def test_parse_finds_transcript_wherever_it_lives():
    flat = parse_event(json.dumps({"type": "transcript.final", "transcript": "hello"}))
    nested = parse_event(json.dumps(
        {"type": "transcript.partial", "data": {"transcript": "नमस्ते", "language_code": "hi-IN"}}
    ))
    text_field = parse_event(json.dumps({"type": "transcript.final", "text": "hi there"}))
    assert flat.text == "hello"
    assert nested.text == "नमस्ते" and nested.language_code == "hi-IN"
    assert text_field.text == "hi there"


def test_parse_garbage_is_other_not_crash():
    assert parse_event("not json at all").kind == "other"
    assert parse_event(json.dumps(["a", "list"])).kind == "other"


def test_audio_message_roundtrips_pcm():
    pcm = bytes(range(64))
    msg = json.loads(audio_message(pcm))
    assert msg["type"] == "audio"
    assert base64.b64decode(msg["data"]) == pcm


@pytest.mark.anyio
async def test_session_against_fake_server():
    import websockets

    received = []

    async def fake_sarvam(ws):
        assert ws.request.headers.get("api-subscription-key") == "k"
        async for message in ws:
            received.append(json.loads(message))
            await ws.send(json.dumps({"type": "transcript.partial", "transcript": "what is"}))
            await ws.send(json.dumps({"type": "vad.speech_end"}))
            await ws.send(json.dumps({"type": "transcript.final", "transcript": "what is a corporation"}))
            break

    async with websockets.serve(fake_sarvam, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        stt = RealtimeSTT(api_key="k", url=f"ws://127.0.0.1:{port}/ws")
        events = []
        async with stt:
            await stt.send_audio(b"\x00\x01" * 320)
            async for event in stt.events():
                events.append(event)
                if event.kind == "final":
                    break

    assert received[0]["type"] == "audio"
    kinds = [e.kind for e in events]
    assert kinds == ["partial", "speech_end", "final"]
    assert events[-1].text == "what is a corporation"


@pytest.fixture
def anyio_backend():
    return "asyncio"
