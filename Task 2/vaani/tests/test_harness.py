import time

from vaani.harness import AnswerPayload, Pipeline, Refusal, Stage


def make_answer(ctx):
    return {"answer": AnswerPayload(text="hello", passage_ids=["p1"], kind="extractive")}


def test_happy_path_traces_every_stage():
    p = Pipeline([
        Stage("embed", lambda ctx: {"vec": [1.0]}),
        Stage("answer", make_answer),
    ])
    result = p.run({"query": "hi"})
    assert isinstance(result.answer, AnswerPayload)
    assert result.answer.text == "hello"
    assert [e.stage for e in result.trace] == ["embed", "answer"]
    assert all(e.outcome == "ok" for e in result.trace)
    assert all(e.dur_ms >= 0 for e in result.trace)
    assert result.total_ms >= max(e.dur_ms for e in result.trace)


def test_timeout_triggers_fallback():
    def slow(ctx):
        time.sleep(0.2)
        return {"answer": AnswerPayload(text="slow", kind="generative")}

    fallback = Stage("extractive", make_answer)
    p = Pipeline([Stage("generate", slow, timeout_ms=30, fallback=fallback)])
    result = p.run({})
    assert isinstance(result.answer, AnswerPayload)
    assert result.answer.text == "hello"
    events = {e.stage: e for e in result.trace}
    assert events["generate"].outcome == "fallback"
    assert "timeout" in events["generate"].detail


def test_error_without_fallback_refuses_not_raises():
    def boom(ctx):
        raise ValueError("kaput")

    p = Pipeline([Stage("boom", boom), Stage("answer", make_answer)])
    result = p.run({})
    assert isinstance(result.answer, Refusal)
    assert result.answer.reason_code == "stage_error:boom"
    # pipeline stopped, the answer stage never ran
    assert [e.stage for e in result.trace] == ["boom"]


def test_refusal_short_circuits_later_stages():
    ran = []

    def guard(ctx):
        return Refusal(reason_code="unsafe_input", message="blocked")

    def never(ctx):
        ran.append(True)
        return {}

    p = Pipeline([Stage("guard", guard), Stage("later", never)])
    result = p.run({})
    assert isinstance(result.answer, Refusal)
    assert result.answer.reason_code == "unsafe_input"
    assert ran == []


def test_retry_then_success():
    calls = {"n": 0}

    def flaky(ctx):
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionError("blip")
        return {"answer": AnswerPayload(text="third time lucky")}

    p = Pipeline([Stage("net", flaky, retries=2)])
    result = p.run({})
    assert isinstance(result.answer, AnswerPayload)
    assert calls["n"] == 3
