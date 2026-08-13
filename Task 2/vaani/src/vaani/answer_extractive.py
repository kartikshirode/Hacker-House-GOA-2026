"""Extractive answering: pick the best sentence out of the top hits.

This is the latency floor of the whole system. No model call, just
token overlap plus a position prior, so it always returns in well
under 10ms and serves as the fallback when generation is skipped,
times out or fails the groundedness gate.
"""

from __future__ import annotations

import re

from vaani.harness import AnswerPayload
from vaani.retriever import Hit

_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_SENT_SPLIT = re.compile(r"(?<=[.!?।])\s+")
_TOKEN = re.compile(r"\w+", re.UNICODE)


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN.findall(text or "")}


def answer(hits: list[Hit], query: str, max_hits: int = 3) -> AnswerPayload:
    """Best-overlap sentence from the top hits, in the query's script."""
    use_translated = bool(_DEVANAGARI.search(query))
    q_tokens = _tokens(query)

    best_sent, best_score, best_pid = "", -1.0, ""
    for hit in hits[:max_hits]:
        text = (hit.tr_text if use_translated else hit.eng_text) or hit.eng_text
        sents = [s.strip() for s in _SENT_SPLIT.split(text) if len(s.strip()) >= 15]
        for pos, sent in enumerate(sents):
            overlap = len(q_tokens & _tokens(sent))
            # earlier sentences in higher-ranked passages win ties
            score = overlap + 0.3 * hit.score - 0.01 * pos
            if score > best_score:
                best_sent, best_score, best_pid = sent, score, hit.passage_id

    if not best_sent:
        best_hit = hits[0]
        best_sent = ((best_hit.tr_text if use_translated else best_hit.eng_text)
                     or best_hit.eng_text)[:300]
        best_pid = best_hit.passage_id

    return AnswerPayload(
        text=best_sent,
        passage_ids=[best_pid],
        kind="extractive",
        language="hi" if use_translated else "en",
    )
