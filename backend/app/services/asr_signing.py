"""Short-lived HMAC signatures for provider-only audio downloads."""
from __future__ import annotations

import hashlib
import hmac
import time
from urllib.parse import urlencode

from app.config import Settings


def _message(job_id: str, expires: int) -> bytes:
    return f"{job_id}:{expires}".encode("utf-8")


def sign_audio_download(job_id: str, expires: int, secret: str) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        _message(job_id, expires),
        hashlib.sha256,
    ).hexdigest()


def verify_audio_download(
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
    expected = sign_audio_download(job_id, expires, secret)
    return hmac.compare_digest(expected, signature)


def build_signed_audio_url(
    job_id: str,
    settings: Settings,
    *,
    now: int | None = None,
) -> str:
    current = int(time.time()) if now is None else now
    expires = current + settings.ASR_AUDIO_URL_TTL_SECONDS
    signature = sign_audio_download(
        job_id,
        expires,
        settings.ASR_AUDIO_SIGNING_SECRET,
    )
    base = settings.ASR_PUBLIC_BASE_URL.rstrip("/")
    query = urlencode({"expires": expires, "signature": signature})
    return f"{base}/api/asr-provider/audio/{job_id}?{query}"


def build_signed_diagnostic_audio_url(
    settings: Settings,
    *,
    now: int | None = None,
) -> str:
    current = int(time.time()) if now is None else now
    expires = current + settings.ASR_AUDIO_URL_TTL_SECONDS
    signature = sign_audio_download(
        "diagnostic",
        expires,
        settings.ASR_AUDIO_SIGNING_SECRET,
    )
    base = settings.ASR_PUBLIC_BASE_URL.rstrip("/")
    query = urlencode({"expires": expires, "signature": signature})
    return f"{base}/api/asr-provider/diagnostic-audio?{query}"
