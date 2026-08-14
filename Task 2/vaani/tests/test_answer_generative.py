import httpx
import pytest

from vaani.answer_generative import (
    GenerationClient,
    answer,
    build_user_prompt,
)
from vaani.harness import AnswerPayload, Refusal
from vaani.retriever import Hit


def make_hit(pid="p1", eng="A corporation is a legal entity.", tr="निगम एक कानूनी इकाई है।"):
    return Hit(passage_id=pid, eng_text=eng, tr_text=tr, score=0.9)


def client_returning(content):
    def handler(request):
        body = request.read().decode()
        assert "chat/completions" in str(request.url)
        return httpx.Response(200, json={
            "choices": [{"message": {"content": content}}]
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


def test_prompt_uses_translated_text_for_devanagari_query():
    prompt = build_user_prompt([make_hit()], "निगम क्या है")
    assert "निगम एक कानूनी इकाई है।" in prompt
    assert "Question: निगम क्या है" in prompt


def test_prompt_uses_english_for_latin_query():
    prompt = build_user_prompt([make_hit()], "what is a corporation")
    assert "[1] A corporation is a legal entity." in prompt
