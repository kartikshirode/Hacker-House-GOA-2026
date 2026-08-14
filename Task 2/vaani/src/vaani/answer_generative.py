"""Generative answering against an OpenAI-compatible endpoint.

vLLM serves the model on the same box (default localhost:8001), so the
HTTP hop costs well under a millisecond. The client stays a thin httpx
wrapper: tests inject a mock transport, and the endpoint can be swapped
for any OpenAI-compatible server without touching the pipeline.

Contract with the pipeline: returns AnswerPayload on success, Refusal
with reason model_abstained when the model says the context has no
answer. Transport errors and timeouts raise, which the harness turns
into the extractive fallback.
"""

from __future__ import annotations

import re

import httpx

from vaani.harness import AnswerPayload, Refusal
from vaani.retriever import Hit

NO_ANSWER_TOKEN = "NO_ANSWER"
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")

SYSTEM_PROMPT = (
    "You answer questions using ONLY the numbered context passages. "
    "Reply with the answer alone, one short sentence, in the same "
    f"language as the question. If the passages do not contain the answer, reply exactly {NO_ANSWER_TOKEN}."
)


def build_user_prompt(hits: list[Hit], query: str, max_passages: int = 3,
                      max_chars: int = 500) -> str:
    use_translated = bool(_DEVANAGARI.search(query))
    lines = []
    for i, hit in enumerate(hits[:max_passages], start=1):
        text = (hit.tr_text if use_translated else hit.eng_text) or hit.eng_text
        lines.append(f"[{i}] {text[:max_chars]}")
    lines.append(f"Question: {query}")
    return "\n".join(lines)


class GenerationClient:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8001/v1",
        model: str = "Qwen/Qwen3-1.7B",
        timeout_s: float = 2.0,
        max_tokens: int = 60,
        client: httpx.Client | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.max_tokens = max_tokens
        self.client = client or httpx.Client(timeout=timeout_s)

    def chat(self, system: str, user: str) -> str:
        response = self.client.post(
            f"{self.base_url}/chat/completions",
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "max_tokens": self.max_tokens,
                "temperature": 0.0,
                "chat_template_kwargs": {"enable_thinking": False},
            },
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"].strip()


def answer(client: GenerationClient, hits: list[Hit], query: str) -> AnswerPayload | Refusal:
    text = client.chat(SYSTEM_PROMPT, build_user_prompt(hits, query))
    if NO_ANSWER_TOKEN in text or not text:
        return Refusal(
            reason_code="model_abstained",
            message="the retrieved passages do not answer this",
        )
    return AnswerPayload(
        text=text,
        passage_ids=[h.passage_id for h in hits[:3]],
        kind="generative",
        language="hi" if _DEVANAGARI.search(query) else "en",
    )
