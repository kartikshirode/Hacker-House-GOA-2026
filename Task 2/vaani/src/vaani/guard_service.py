"""GPU sidecar for the two model-backed guards.

Runs next to vLLM on the compute node (the models are tiny next to the
LLM). The app on the login node calls it over the cluster LAN.

  /classify_input      prompt injection score for the raw query
                       (protectai/deberta-v3-base-prompt-injection-v2)
  /score_groundedness  HHEM-2.1 entailment of answer given passages
                       (vectara/hallucination_evaluation_model)

Start:  VAANI_GUARD_DEVICE=cuda uvicorn vaani.guard_service:app --port 8002
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from pydantic import BaseModel

INJECTION_MODEL = "protectai/deberta-v3-base-prompt-injection-v2"
HHEM_MODEL = "vectara/hallucination_evaluation_model"

app = FastAPI(title="vaani-guards")
_models: dict = {}


def _device() -> str:
    return os.environ.get("VAANI_GUARD_DEVICE", "cpu")


def _injection_pipe():
    if "injection" not in _models:
        from transformers import pipeline

        _models["injection"] = pipeline(
            "text-classification",
            model=INJECTION_MODEL,
            device=0 if _device() == "cuda" else -1,
            truncation=True,
            max_length=512,
        )
    return _models["injection"]


def _hhem():
    if "hhem" not in _models:
        from transformers import AutoModelForSequenceClassification

        model = AutoModelForSequenceClassification.from_pretrained(
            HHEM_MODEL, trust_remote_code=True
        )
        if _device() == "cuda":
            model = model.to("cuda")
        _models["hhem"] = model
    return _models["hhem"]


class InputCheck(BaseModel):
    text: str


class GroundingCheck(BaseModel):
    answer: str
    contexts: list[str]


@app.on_event("startup")
def warm_models():
    # lazy first-request loading costs tens of seconds; pay it at boot
    _injection_pipe()("warmup query")
    _hhem().predict([("warmup context", "warmup answer")])


@app.get("/healthz")
def healthz():
    return {"ok": True, "device": _device(), "warm": bool(_models)}


@app.post("/classify_input")
def classify_input(body: InputCheck):
    result = _injection_pipe()(body.text[:2000])[0]
    injection = result["label"] == "INJECTION"
    return {
        "malicious": bool(injection and result["score"] > 0.8),
        "label": result["label"],
        "score": round(float(result["score"]), 4),
    }


@app.post("/score_groundedness")
def score_groundedness(body: GroundingCheck):
    premise = " ".join(body.contexts)[:4000]
    pairs = [(premise, body.answer)]
    score = float(_hhem().predict(pairs)[0])
    return {"score": round(score, 4)}
