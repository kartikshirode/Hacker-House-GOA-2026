"""Guard gates.

GuardClient talks to the GPU sidecar (guard_service.py) when a url is
configured; without one, checks degrade to permissive stubs so the
pipeline shape stays identical in development.

Failure policy, chosen deliberately: if the guard service is down or
slow, input checks FAIL OPEN (the query proceeds, verdict carries the
reason) because retrieval confidence and model abstention still stand
between a bad query and a bad answer. The groundedness gate also fails
open but marks the verdict, and the server surfaces the flag in the
trace so an ungraded answer is never silently presented as graded.
"""

from __future__ import annotations

import httpx
from pydantic import BaseModel


class GuardVerdict(BaseModel):
    allowed: bool
    reason: str = ""
    score: float | None = None
    checked: bool = False  # False means a stub or fail-open path answered


class GuardClient:
    def __init__(
        self,
        base_url: str | None,
        groundedness_threshold: float = 0.5,
        timeout_s: float = 0.4,
        client: httpx.Client | None = None,
    ):
        self.base_url = base_url.rstrip("/") if base_url else None
        self.threshold = groundedness_threshold
        self.client = client or httpx.Client(timeout=timeout_s)

    def check_input(self, query: str) -> GuardVerdict:
        if not query or not query.strip():
            return GuardVerdict(allowed=False, reason="empty_query", checked=True)
        if self.base_url is None:
            return GuardVerdict(allowed=True, reason="stub")
        try:
            data = self.client.post(
                f"{self.base_url}/classify_input", json={"text": query}
            ).json()
            return GuardVerdict(
                allowed=not data["malicious"],
                reason=data["label"],
                score=data["score"],
                checked=True,
            )
        except Exception as exc:  # noqa: BLE001 fail open, see module docstring
            return GuardVerdict(allowed=True, reason=f"guard_error:{type(exc).__name__}")

    def check_output(self, answer_text: str, context_texts: list[str]) -> GuardVerdict:
        if self.base_url is None:
            return GuardVerdict(allowed=True, reason="stub")
        try:
            data = self.client.post(
                f"{self.base_url}/score_groundedness",
                json={"answer": answer_text, "contexts": context_texts},
            ).json()
            score = float(data["score"])
            return GuardVerdict(
                allowed=score >= self.threshold,
                reason="hhem",
                score=score,
                checked=True,
            )
        except Exception as exc:  # noqa: BLE001
            return GuardVerdict(allowed=True, reason=f"guard_error:{type(exc).__name__}")
