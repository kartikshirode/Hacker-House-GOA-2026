"""Guard gates. Interfaces are final; the model-backed checks land in
phase B (Prompt-Guard input classifier, HHEM groundedness). The stubs
keep the pipeline shape and tracing honest until then.
"""

from __future__ import annotations

from pydantic import BaseModel


class GuardVerdict(BaseModel):
    allowed: bool
    reason: str = ""
    score: float | None = None


def check_input(query: str) -> GuardVerdict:
    """Injection/unsafe-input gate. Stub: allows everything non-empty."""
    if not query or not query.strip():
        return GuardVerdict(allowed=False, reason="empty_query")
    return GuardVerdict(allowed=True)


def check_output(answer_text: str, context_texts: list[str]) -> GuardVerdict:
    """Groundedness gate. Stub: allows everything until HHEM lands."""
    return GuardVerdict(allowed=True)
