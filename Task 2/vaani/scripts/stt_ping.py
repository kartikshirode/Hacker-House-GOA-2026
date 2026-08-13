"""One tiny real call to verify the Sarvam key and response contract.

Sends 1 second of generated audio (about ₹0.008 of credit) and prints
the parsed response plus total estimated spend so far. Run once after
setting SARVAM_API_KEY in .env; everything else should use mock mode.
"""

import io
import math
import struct
import wave

from vaani.stt import SarvamSTT


def tone_wav(seconds: float = 1.0, hz: float = 440.0, rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        for i in range(int(seconds * rate)):
            sample = int(12000 * math.sin(2 * math.pi * hz * i / rate))
            w.writeframes(struct.pack("<h", sample))
    return buf.getvalue()


def main() -> None:
    stt = SarvamSTT(mock=False)
    audio = tone_wav()
    result = stt.transcribe_bytes(audio, filename="ping.wav", audio_seconds=1.0)
    print(f"transcript: {result.text!r}")
    print(f"language_code: {result.language_code}")
    print(f"request_id: {result.request_id}")
    print(f"cached: {result.cached}  api_ms: {result.api_ms:.0f}")
    print(f"estimated total spend so far: ₹{stt.spent_rupees()}")


if __name__ == "__main__":
    main()
