"""Sarvam speech-to-text REST client with strict credit discipline.

The free tier is ₹100 at ₹30 per audio hour, so this client never
spends a paisa twice:

- every transcription is cached on disk by audio hash; replays are free
- mock mode (VAANI_STT_MOCK=1) serves development and tests with zero
  network calls; a sidecar .txt next to the audio file supplies the
  expected transcript
- every real call appends seconds + estimated cost to a usage ledger

The realtime websocket client lives in stt_realtime.py.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

import httpx
from pydantic import BaseModel

try:  # pick up SARVAM_API_KEY from Task 2/vaani/.env when present
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

SARVAM_STT_URL = "https://api.sarvam.ai/speech-to-text"
RUPEES_PER_SECOND = 30.0 / 3600.0  # ₹30 per audio hour

# A public link with no ceiling can drain the balance in minutes, so the
# caps are on by default and opting out means saying so out loud.
DEFAULT_BUDGET_RUPEES = 25.0
DEFAULT_MAX_CLIP_BYTES = 1_000_000


class BudgetExceeded(RuntimeError):
    """Raised instead of spending past a cap. Callers turn this into a
    refusal; it is never a 500, because refusing on purpose is the
    designed behaviour here, not a fault."""


class TranscriptResult(BaseModel):
    text: str
    language_code: str | None = None
    request_id: str | None = None
    cached: bool = False
    mock: bool = False
    api_ms: float = 0.0


class SarvamSTT:
    def __init__(
        self,
        api_key: str | None = None,
        model: str = "saaras:v3",
        cache_dir: str | Path = "data/stt_cache",
        usage_log: str | Path = "data/stt_usage.jsonl",
        mock: bool | None = None,
        timeout_s: float = 20.0,
    ):
        # None means "use the environment"; an explicit empty string means
        # "no key", so tests can never leak onto the real API
        self.api_key = api_key if api_key is not None else os.environ.get("SARVAM_API_KEY", "")
        self.model = model
        self.cache_dir = Path(cache_dir)
        self.usage_log = Path(usage_log)
        self.mock = mock if mock is not None else os.environ.get("VAANI_STT_MOCK") == "1"
        self.client = httpx.Client(timeout=timeout_s)
        # 0 disables a cap; unset falls back to the defaults above
        self.budget_rupees = _env_float("VAANI_STT_BUDGET_RUPEES", DEFAULT_BUDGET_RUPEES)
        self.max_clip_bytes = int(_env_float("VAANI_STT_MAX_CLIP_BYTES", DEFAULT_MAX_CLIP_BYTES))
        self._spent: float | None = None  # ledger total, read once then cached

    # -- helpers ---------------------------------------------------------

    def _cache_key(self, audio: bytes, language: str) -> str:
        h = hashlib.sha256()
        h.update(audio)
        h.update(f"|{self.model}|{language}".encode())
        return h.hexdigest()

    def _cache_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    def _log_usage(self, seconds: float) -> None:
        self.usage_log.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "audio_seconds": round(seconds, 2),
            "est_rupees": round(seconds * RUPEES_PER_SECOND, 4),
        }
        with self.usage_log.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        self._spent = None  # force a re-read; only happens after a real call

    def spent_rupees(self) -> float:
        if self._spent is not None:
            return self._spent
        total = 0.0
        if self.usage_log.exists():
            for line in self.usage_log.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    total += json.loads(line)["est_rupees"]
        self._spent = round(total, 4)
        return self._spent

    def budget_left(self) -> float:
        """Rupees left under the ceiling; inf when uncapped."""
        if not self.budget_rupees:
            return float("inf")
        return round(self.budget_rupees - self.spent_rupees(), 4)

    # -- transcription ---------------------------------------------------

    def transcribe_file(self, path: str | Path, language: str = "unknown") -> TranscriptResult:
        path = Path(path)
        audio = path.read_bytes()
        if self.mock:
            sidecar = path.with_suffix(".txt")
            text = sidecar.read_text(encoding="utf-8").strip() if sidecar.exists() \
                else f"mock transcript for {path.stem}"
            return TranscriptResult(text=text, language_code="hi-IN", mock=True)
        return self.transcribe_bytes(audio, filename=path.name, language=language,
                                     audio_seconds=_wav_seconds(audio))

    def transcribe_bytes(
        self,
        audio: bytes,
        filename: str = "audio.wav",
        language: str = "unknown",
        audio_seconds: float | None = None,
    ) -> TranscriptResult:
        if self.mock:
            return TranscriptResult(text="mock transcript", language_code="hi-IN", mock=True)

        key = self._cache_key(audio, language)
        cached = self._cache_path(key)
        if cached.exists():
            data = json.loads(cached.read_text(encoding="utf-8"))
            return TranscriptResult(**{**data, "cached": True})

        if not self.api_key:
            raise RuntimeError(
                "SARVAM_API_KEY is not set; put it in Task 2/vaani/.env "
                "or export it before making real STT calls"
            )

        # both checks sit after the cache lookup on purpose: a replay costs
        # nothing and stays answerable even once the budget is gone
        if self.max_clip_bytes and len(audio) > self.max_clip_bytes:
            raise BudgetExceeded(
                f"clip is {len(audio)} bytes, over the {self.max_clip_bytes} byte cap"
            )
        if self.budget_left() <= 0:
            raise BudgetExceeded(
                f"stt budget spent: {self.spent_rupees()} of {self.budget_rupees} rupees"
            )

        t0 = time.perf_counter()
        response = self.client.post(
            SARVAM_STT_URL,
            headers={"api-subscription-key": self.api_key},
            files={"file": (filename, audio, "audio/wav")},
            data={"model": self.model, "language_code": language},
        )
        response.raise_for_status()
        body = response.json()
        result = TranscriptResult(
            text=body.get("transcript", ""),
            language_code=body.get("language_code"),
            request_id=body.get("request_id"),
            api_ms=(time.perf_counter() - t0) * 1000,
        )

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cached.write_text(
            result.model_dump_json(exclude={"cached", "mock"}), encoding="utf-8"
        )
        self._log_usage(audio_seconds if audio_seconds is not None else len(audio) / 32000)
        return result


def _wav_seconds(audio: bytes) -> float:
    """Duration of a wav payload; falls back to a 16kHz mono pcm guess."""
    try:
        import io
        import wave

        with wave.open(io.BytesIO(audio)) as w:
            return w.getnframes() / w.getframerate()
    except Exception:
        return len(audio) / 32000  # 16kHz * 2 bytes


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        return default
