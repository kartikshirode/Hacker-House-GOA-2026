import json

import httpx
import pytest

from vaani.stt import RUPEES_PER_SECOND, SarvamSTT, TranscriptResult


def make_stt(tmp_path, handler, mock=False):
    stt = SarvamSTT(
        api_key="test-key",
        cache_dir=tmp_path / "cache",
        usage_log=tmp_path / "usage.jsonl",
        mock=mock,
    )
    if handler is not None:
        stt.client = httpx.Client(transport=httpx.MockTransport(handler))
    return stt


def sarvam_ok(request):
    assert request.headers["api-subscription-key"] == "test-key"
    return httpx.Response(200, json={
        "transcript": "निगम क्या है",
        "language_code": "hi-IN",
        "request_id": "req-1",
    })


def test_rest_call_parses_and_logs_usage(tmp_path):
    stt = make_stt(tmp_path, sarvam_ok)
    result = stt.transcribe_bytes(b"fake-audio", audio_seconds=6.0)
    assert result.text == "निगम क्या है"
    assert result.language_code == "hi-IN"
    assert not result.cached and not result.mock
    lines = (tmp_path / "usage.jsonl").read_text(encoding="utf-8").splitlines()
    entry = json.loads(lines[0])
    assert entry["audio_seconds"] == 6.0
    assert entry["est_rupees"] == round(6.0 * RUPEES_PER_SECOND, 4)
    assert stt.spent_rupees() == round(6.0 * RUPEES_PER_SECOND, 2)


def test_second_call_hits_cache_not_network(tmp_path):
    calls = {"n": 0}

    def counting(request):
        calls["n"] += 1
        return sarvam_ok(request)

    stt = make_stt(tmp_path, counting)
    first = stt.transcribe_bytes(b"same-audio", audio_seconds=3.0)
    second = stt.transcribe_bytes(b"same-audio", audio_seconds=3.0)
    assert calls["n"] == 1
    assert second.cached and second.text == first.text
    # only the real call is billed
    assert len((tmp_path / "usage.jsonl").read_text(encoding="utf-8").splitlines()) == 1


def test_mock_mode_never_touches_network(tmp_path):
    def explode(request):
        raise AssertionError("network call in mock mode")

    stt = make_stt(tmp_path, explode, mock=True)
    result = stt.transcribe_bytes(b"whatever")
    assert result.mock and result.text


def test_mock_file_reads_sidecar_transcript(tmp_path):
    wav = tmp_path / "q1.wav"
    wav.write_bytes(b"not-really-audio")
    (tmp_path / "q1.txt").write_text("what is a corporation", encoding="utf-8")
    stt = make_stt(tmp_path, None, mock=True)
    result = stt.transcribe_file(wav)
    assert result.text == "what is a corporation"


def test_missing_key_raises_before_spending(tmp_path):
    stt = SarvamSTT(api_key="", cache_dir=tmp_path, usage_log=tmp_path / "u.jsonl", mock=False)
    with pytest.raises(RuntimeError, match="SARVAM_API_KEY"):
        stt.transcribe_bytes(b"audio")
