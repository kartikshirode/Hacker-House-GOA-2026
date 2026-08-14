"""Generative answering against an OpenAI-compatible endpoint.

vLLM serves the model on the same box (default localhost:8001), so the
HTTP hop costs well under a millisecond. The client stays a thin httpx
wrapper: tests inject a mock transport, and the endpoint can be swapped
for any OpenAI-compatible server without touching the pipeline.

Contract with the pipeline: returns AnswerPayload on success, Refusal
with reason model_abstained when the model says the context has no
answer. Transport errors, truncation and empty generations raise, which
the harness turns into the extractive fallback.

Streaming: chat_stream forwards token deltas to a callback, but holds
them until the accumulated text can no longer be the NO_ANSWER sentinel
or a thinking tag. The caller never shows text that the refusal path
would have to retract.
"""

from __future__ import annotations

import json
import re
import time
from typing import Callable

import httpx

from vaani.harness import AnswerPayload, Refusal
from vaani.retriever import Hit

NO_ANSWER_TOKEN = "NO_ANSWER"
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL)

# Devanagari costs roughly 2 to 4 tokens per word on the Qwen3 tokenizer,
# so a 20 word Hindi answer needs far more headroom than English
MAX_TOKENS_EN = 32
MAX_TOKENS_HI = 64

SYSTEM_PROMPT = (
    "You answer questions using ONLY the numbered context passages. "
    "Reply with the answer alone, one short sentence in under 20 words, in the same "
    f"language as the question. If the passages do not contain the answer, reply exactly {NO_ANSWER_TOKEN}."
)


class TruncatedAnswer(RuntimeError):
    """Generation stopped at the token cap. Raising sends the query to
    the extractive fallback instead of showing a cut-off sentence."""


def build_user_prompt(hits: list[Hit], query: str, max_passages: int = 3,
                      max_chars: int = 500) -> str:
    use_translated = bool(_DEVANAGARI.search(query))
    lines = []
    for i, hit in enumerate(hits[:max_passages], start=1):
        text = (hit.tr_text if use_translated else hit.eng_text) or hit.eng_text
        lines.append(f"[{i}] {text[:max_chars]}")
    lines.append(f"Question: {query}")
    return "\n".join(lines)


def _postprocess(raw: str) -> str:
    text = _THINK_BLOCK.sub("", raw).strip()
    if "<think>" in text:
        # an unterminated block means the visible text is reasoning,
        # not an answer
        raise ValueError("unterminated think block in generation")
    return text


def _held_back(acc: str) -> bool:
    """True while the accumulated stream could still turn into NO_ANSWER
    or a thinking tag. Held tokens are never surfaced."""
    head = acc.lstrip()
    if not head:
        return True
    if head.startswith("<"):
        return True
    return NO_ANSWER_TOKEN.startswith(head[: len(NO_ANSWER_TOKEN)])


class GenerationClient:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8001/v1",
        model: str = "Qwen/Qwen3-1.7B",
        timeout_s: float = 2.0,
        max_tokens: int = MAX_TOKENS_EN,
        client: httpx.Client | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.max_tokens = max_tokens
        self.client = client or httpx.Client(timeout=timeout_s)
        if self.model == "auto":
            self.model = self._resolve_model()

    def _resolve_model(self) -> str:
        # boot-time discovery must survive a server that is still loading;
        # the tight per-request timeout would fail every cold start
        last: Exception | None = None
        for attempt in range(5):
            try:
                served = self.client.get(f"{self.base_url}/models", timeout=5.0).json()
                return served["data"][0]["id"]
            except Exception as exc:  # noqa: BLE001
                last = exc
                if attempt < 4:
                    time.sleep(1.0)
        raise RuntimeError(f"could not resolve served model at {self.base_url}: {last}")

    def _body(self, system: str, user: str, max_tokens: int | None,
              stream: bool = False) -> dict:
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens or self.max_tokens,
            "temperature": 0.0,
            "stop": ["\n"],
            "chat_template_kwargs": {"enable_thinking": False},
        }
        if stream:
            body["stream"] = True
        return body

    def chat(self, system: str, user: str, max_tokens: int | None = None) -> str:
        response = self.client.post(
            f"{self.base_url}/chat/completions",
            json=self._body(system, user, max_tokens),
        )
        response.raise_for_status()
        choice = response.json()["choices"][0]
        text = _postprocess(choice["message"]["content"])
        if choice.get("finish_reason") == "length":
            raise TruncatedAnswer(f"hit the {max_tokens or self.max_tokens} token cap")
        return text

    def chat_stream(self, system: str, user: str,
                    on_token: Callable[[str], None],
                    max_tokens: int | None = None) -> str:
        acc = ""
        flushed = 0
        finish = None
        with self.client.stream(
            "POST", f"{self.base_url}/chat/completions",
            json=self._body(system, user, max_tokens, stream=True),
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[len("data:"):].strip()
                if data == "[DONE]":
                    break
                choice = json.loads(data)["choices"][0]
                finish = choice.get("finish_reason") or finish
                delta = (choice.get("delta") or {}).get("content")
                if not delta:
                    continue
                acc += delta
                if _held_back(acc):
                    continue
                if len(acc) > flushed:
                    on_token(acc[flushed:])
                    flushed = len(acc)
        text = _postprocess(acc)
        if finish == "length":
            raise TruncatedAnswer(f"hit the {max_tokens or self.max_tokens} token cap")
        return text


def answer(client: GenerationClient, hits: list[Hit], query: str,
           on_token: Callable[[str], None] | None = None) -> AnswerPayload | Refusal:
    hindi = bool(_DEVANAGARI.search(query))
    max_tokens = MAX_TOKENS_HI if hindi else None
    user = build_user_prompt(hits, query)
    if on_token is None:
        text = client.chat(SYSTEM_PROMPT, user, max_tokens=max_tokens)
    else:
        text = client.chat_stream(SYSTEM_PROMPT, user, on_token, max_tokens=max_tokens)
    if NO_ANSWER_TOKEN in text:
        return Refusal(
            reason_code="model_abstained",
            message="the retrieved passages do not answer this",
        )
    if not text:
        # empty output is an anomaly, not an abstention; raising routes
        # the query to the extractive fallback instead of a refusal
        raise ValueError("empty generation")
    return AnswerPayload(
        text=text,
        passage_ids=[h.passage_id for h in hits[:3]],
        kind="generative",
        language="hi" if hindi else "en",
    )
