from fastapi.testclient import TestClient

from vaani.harness import AnswerPayload, PipelineResult, Refusal, StageEvent
from vaani.server import create_app
from vaani.stt import TranscriptResult


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


def make_client(answer=None, stt=None):
    answer = answer or AnswerPayload(text="a corporation is a legal entity", passage_ids=["abc123"])
    app = create_app(lambda q: fake_result(answer), stt or FakeSTT())
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
    def never_called(q):
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
