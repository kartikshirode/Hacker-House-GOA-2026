from fastapi.testclient import TestClient

from vaani.harness import AnswerPayload, PipelineResult, Refusal, StageEvent
from vaani.server import create_app
from vaani.stt import BudgetExhausted, TranscriptResult


def fake_result(answer):
    return PipelineResult(
        request_id="r1",
        answer=answer,
        trace=[StageEvent(stage="retrieve", started_ns=0, dur_ms=5.0, outcome="ok")],
        total_ms=6.5,
    )


class FakeSTT:
    def __init__(self, text="what is a corporation"):
        self.text = text

    def transcribe_bytes(self, audio, filename="f", language="unknown"):
        return TranscriptResult(text=self.text, language_code="en-IN", mock=True)


def make_client(answer=None, stt=None, **kwargs):
    answer = answer or AnswerPayload(text="a corporation is a legal entity", passage_ids=["abc123"])
    app = create_app(lambda ctx: fake_result(answer), stt or FakeSTT(), **kwargs)
    return TestClient(app)


def test_ask_returns_answer_and_trace():
    client = make_client()
    res = client.post("/api/ask", json={"query": "what is a corporation"})
    assert res.status_code == 200
    body = res.json()
    assert not body["refused"]
    assert body["answer"]["text"].startswith("a corporation")
    assert body["trace"][0]["stage"] == "retrieve"
    assert body["pipeline_ms"] == 6.5


def test_ask_refusal_shape():
    client = make_client(answer=Refusal(reason_code="low_confidence", message="0.1"))
    body = client.post("/api/ask", json={"query": "zz"}).json()
    assert body["refused"]
    assert body["refusal"]["reason_code"] == "low_confidence"
    assert body["answer"] is None


def test_voice_prepends_stt_stage_and_transcript():
    client = make_client()
    res = client.post("/api/voice", files={"file": ("q.webm", b"fake-audio", "audio/webm")})
    body = res.json()
    assert body["transcript"] == "what is a corporation"
    assert body["trace"][0]["stage"] == "stt"
    assert body["trace"][1]["stage"] == "retrieve"
    assert body["total_ms"] >= body["pipeline_ms"]


def test_voice_empty_transcript_refuses_without_pipeline():
    def never_called(ctx):
        raise AssertionError("pipeline ran on an empty transcript")

    app = create_app(never_called, FakeSTT(text=""))
    client = TestClient(app)
    body = client.post(
        "/api/voice", files={"file": ("q.webm", b"fake", "audio/webm")}
    ).json()
    assert body["refused"]
    assert body["refusal"]["reason_code"] == "empty_transcript"


def test_health():
    assert make_client().get("/healthz").json() == {"ok": True}


def test_voice_upload_too_large_refused_before_stt():
    class NeverSTT:
        def transcribe_bytes(self, *a, **k):
            raise AssertionError("stt ran on an oversized clip")

    client = make_client(stt=NeverSTT(), max_upload_bytes=10)
    res = client.post("/api/voice", files={"file": ("q.webm", b"x" * 100, "audio/webm")})
    assert res.status_code == 413
    assert res.json()["refusal"]["reason_code"] == "upload_too_large"


def test_voice_budget_exhausted_becomes_refusal():
    class BrokeSTT:
        def transcribe_bytes(self, *a, **k):
            raise BudgetExhausted("ceiling hit")

    client = make_client(stt=BrokeSTT())
    body = client.post(
        "/api/voice", files={"file": ("q.webm", b"fake", "audio/webm")}
    ).json()
    assert body["refused"]
    assert body["refusal"]["reason_code"] == "stt_budget_exhausted"


def test_voice_access_token_gate():
    client = make_client(access_token="s3cret")
    denied = client.post("/api/voice", files={"file": ("q.webm", b"fake", "audio/webm")})
    assert denied.status_code == 401
    allowed = client.post(
        "/api/voice", files={"file": ("q.webm", b"fake", "audio/webm")},
        headers={"X-Vaani-Key": "s3cret"},
    )
    assert allowed.status_code == 200
    assert not allowed.json()["refused"]


def test_ws_voice_access_token_gate():
    client = make_client(access_token="s3cret", stt_session_factory=FakeSession)
    with client.websocket_connect("/ws/voice") as ws:
        assert ws.receive_json()["message"] == "unauthorized"
    with client.websocket_connect("/ws/voice?key=s3cret") as ws:
        assert ws.receive_json()["type"] == "partial"


class FakeSession:
    """Scripted realtime STT session: two partials, then a final."""

    def __init__(self):
        from vaani.stt_realtime import SpeechEvent

        self.received = []
        self._events = [
            SpeechEvent(kind="partial", text="what is"),
            SpeechEvent(kind="partial", text="what is a corporation"),
            SpeechEvent(kind="speech_end"),
            SpeechEvent(kind="final", text="what is a corporation"),
        ]

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        pass

    async def send_audio(self, frame):
        self.received.append(frame)

    async def events(self):
        for event in self._events:
            yield event


def test_ws_voice_streams_partials_then_result():
    speculated = []

    def speculate(text):
        speculated.append(text)
        return {"speculative_marker": text}

    client = make_client(speculate=speculate, stt_session_factory=FakeSession)
    with client.websocket_connect("/ws/voice") as ws:
        ws.send_bytes(b"\x00\x01" * 160)
        first = ws.receive_json()
        second = ws.receive_json()
        transcript = ws.receive_json()
        result = ws.receive_json()

    assert first == {"type": "partial", "text": "what is"}
    assert second["text"] == "what is a corporation"
    assert transcript["type"] == "transcript"
    assert result["type"] == "result"
    assert result["speculative"] is True
    assert result["answer"]["text"].startswith("a corporation")
    # both partials fired speculative retrieval
    assert speculated == ["what is", "what is a corporation"]


def test_ws_voice_without_factory_reports_unconfigured():
    client = make_client()
    with client.websocket_connect("/ws/voice") as ws:
        msg = ws.receive_json()
    assert msg["type"] == "error"


def test_ws_voice_forwards_generation_tokens():
    def run_pipeline(ctx):
        # a streaming generation stage calls the sink from a worker thread
        ctx["on_token"]("a corporation ")
        ctx["on_token"]("is a legal entity")
        return fake_result(AnswerPayload(text="a corporation is a legal entity"))

    app = create_app(run_pipeline, FakeSTT(), stt_session_factory=FakeSession)
    client = TestClient(app)
    with client.websocket_connect("/ws/voice") as ws:
        msgs = [ws.receive_json() for _ in range(6)]

    types = [m["type"] for m in msgs]
    assert types == ["partial", "partial", "transcript", "token", "token", "result"]
    assert msgs[3]["text"] + msgs[4]["text"] == "a corporation is a legal entity"
    assert msgs[5]["answer"]["text"] == "a corporation is a legal entity"
