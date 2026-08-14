import json

import httpx
import pytest

from vaani.answer_generative import (
    MAX_TOKENS_EN,
    MAX_TOKENS_HI,
    GenerationClient,
    TruncatedAnswer,
    answer,
    build_user_prompt,
)
from vaani.harness import AnswerPayload, Refusal
from vaani.retriever import Hit


def make_hit(pid="p1", eng="A corporation is a legal entity.", tr="निगम एक कानूनी इकाई है।"):
    return Hit(passage_id=pid, eng_text=eng, tr_text=tr, score=0.9)


def client_returning(content, finish_reason="stop", requests_seen=None):
    def handler(request):
        if requests_seen is not None:
            requests_seen.append(json.loads(request.read().decode()))
        assert "chat/completions" in str(request.url)
        return httpx.Response(200, json={
            "choices": [{"message": {"content": content},
                         "finish_reason": finish_reason}]
        })

    return GenerationClient(client=httpx.Client(
        transport=httpx.MockTransport(handler), timeout=2.0
    ))


def test_answer_returns_generative_payload():
    result = answer(client_returning("A corporation is a legal entity."),
                    [make_hit()], "what is a corporation")
    assert isinstance(result, AnswerPayload)
    assert result.kind == "generative"
    assert result.language == "en"
    assert result.passage_ids == ["p1"]


def test_no_answer_token_becomes_refusal():
    result = answer(client_returning("NO_ANSWER"), [make_hit()], "who is zzz")
    assert isinstance(result, Refusal)
    assert result.reason_code == "model_abstained"


def test_transport_error_raises_for_harness_fallback():
    def boom(request):
        raise httpx.ConnectError("vllm down")

    client = GenerationClient(client=httpx.Client(transport=httpx.MockTransport(boom)))
    with pytest.raises(httpx.ConnectError):
        answer(client, [make_hit()], "q")


def test_english_request_uses_default_cap():
    seen = []
    answer(client_returning("Fine.", requests_seen=seen),
           [make_hit()], "what is a corporation")
    assert seen[0]["max_tokens"] == MAX_TOKENS_EN


def test_hindi_request_gets_larger_cap():
    seen = []
    answer(client_returning("ठीक है।", requests_seen=seen),
           [make_hit()], "निगम क्या है")
    assert seen[0]["max_tokens"] == MAX_TOKENS_HI


def test_length_finish_raises_truncated():
    with pytest.raises(TruncatedAnswer):
        answer(client_returning("half an ans", finish_reason="length"),
               [make_hit()], "q")


def test_empty_generation_raises_not_refuses():
    # a bare newline before the stop token yields empty content; that is
    # an anomaly for the fallback, not an abstention
    with pytest.raises(ValueError):
        answer(client_returning(""), [make_hit()], "q")


def test_think_block_is_stripped():
    result = answer(client_returning("<think>reasoning here</think>The answer."),
                    [make_hit()], "q")
    assert result.text == "The answer."


def test_unterminated_think_raises():
    with pytest.raises(ValueError):
        answer(client_returning("<think>leaked reasoning"), [make_hit()], "q")


def test_prompt_uses_translated_text_for_devanagari_query():
    prompt = build_user_prompt([make_hit()], "निगम क्या है")
    assert "निगम एक कानूनी इकाई है।" in prompt
    assert "Question: निगम क्या है" in prompt


def test_prompt_uses_english_for_latin_query():
    prompt = build_user_prompt([make_hit()], "what is a corporation")
    assert "[1] A corporation is a legal entity." in prompt


# ---- streaming ------------------------------------------------------

def sse_bytes(deltas, finish_reason="stop"):
    lines = []
    for d in deltas:
        lines.append("data: " + json.dumps(
            {"choices": [{"delta": {"content": d}, "finish_reason": None}]}))
        lines.append("")
    lines.append("data: " + json.dumps(
        {"choices": [{"delta": {}, "finish_reason": finish_reason}]}))
    lines.append("")
    lines.append("data: [DONE]")
    lines.append("")
    return "\n".join(lines).encode()


def streaming_client(deltas, finish_reason="stop"):
    def handler(request):
        body = json.loads(request.read().decode())
        assert body.get("stream") is True
        return httpx.Response(200, content=sse_bytes(deltas, finish_reason))

    return GenerationClient(client=httpx.Client(
        transport=httpx.MockTransport(handler), timeout=2.0
    ))


def test_stream_forwards_tokens_and_returns_text():
    tokens = []
    client = streaming_client(["A corp", "oration is", " a legal entity."])
    result = answer(client, [make_hit()], "what is a corporation",
                    on_token=tokens.append)
    assert isinstance(result, AnswerPayload)
    assert result.text == "A corporation is a legal entity."
    assert "".join(tokens) == "A corporation is a legal entity."


def test_stream_holds_back_no_answer_sentinel():
    tokens = []
    client = streaming_client(["NO_", "ANSWER"])
    result = answer(client, [make_hit()], "who is zzz", on_token=tokens.append)
    assert isinstance(result, Refusal)
    assert tokens == []


def test_stream_length_finish_raises():
    client = streaming_client(["half an ans"], finish_reason="length")
    with pytest.raises(TruncatedAnswer):
        answer(client, [make_hit()], "q", on_token=lambda t: None)
