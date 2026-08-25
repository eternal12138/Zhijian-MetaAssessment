"""Short-lived review playback tickets and lightweight WAV waveforms."""
from __future__ import annotations

from array import array
from functools import lru_cache
import hashlib
import hmac
from pathlib import Path
import sys
import time
import wave


def _message(session_id: str, job_id: str, expires: int) -> bytes:
    return f"review-audio:{session_id}:{job_id}:{expires}".encode("utf-8")


def sign_review_audio(session_id: str, job_id: str, expires: int, secret: str) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        _message(session_id, job_id, expires),
        hashlib.sha256,
    ).hexdigest()


def verify_review_audio(
    session_id: str,
    job_id: str,
    expires: int,
    signature: str,
    secret: str,
    *,
    now: int | None = None,
) -> bool:
    current = int(time.time()) if now is None else now
    if not secret or expires < current:
        return False
    expected = sign_review_audio(session_id, job_id, expires, secret)
    return hmac.compare_digest(expected, signature)


def wav_waveform(path: Path, bars: int = 600) -> tuple[float, list[float]]:
    """Return duration and normalized peaks without loading the whole WAV into memory."""
    stat = path.stat()
    duration, peaks = _cached_wav_waveform(
        str(path.resolve()), stat.st_mtime_ns, stat.st_size, bars
    )
    return duration, list(peaks)


@lru_cache(maxsize=128)
def _cached_wav_waveform(
    resolved_path: str,
    _mtime_ns: int,
    _file_size: int,
    bars: int,
) -> tuple[float, tuple[float, ...]]:
    with wave.open(resolved_path, "rb") as audio:
        if audio.getsampwidth() != 2:
            raise ValueError("仅支持 16 位 PCM WAV 波形预览")
        frame_count = audio.getnframes()
        frame_rate = audio.getframerate()
        if frame_count <= 0 or frame_rate <= 0:
            return 0.0, ()

        peak_count = max(1, min(bars, frame_count))
        peaks: list[float] = []
        for index in range(peak_count):
            start = index * frame_count // peak_count
            end = (index + 1) * frame_count // peak_count
            audio.setpos(start)
            samples = array("h")
            samples.frombytes(audio.readframes(max(1, end - start)))
            if sys.byteorder != "little":
                samples.byteswap()
            peak = max((abs(sample) for sample in samples), default=0)
            peaks.append(min(1.0, peak / 32768.0))

        return frame_count / frame_rate, tuple(peaks)
