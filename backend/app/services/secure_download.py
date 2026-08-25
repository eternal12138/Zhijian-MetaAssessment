"""Short-lived HMAC tickets for large same-origin downloads."""
from __future__ import annotations

import hashlib
import hmac
import time


def _message(scope: str, resource_id: str, expires: int) -> bytes:
    return f"download:{scope}:{resource_id}:{expires}".encode("utf-8")


def sign_download(scope: str, resource_id: str, expires: int, secret: str) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        _message(scope, resource_id, expires),
        hashlib.sha256,
    ).hexdigest()


def verify_download(
    scope: str,
    resource_id: str,
    expires: int,
    signature: str,
    secret: str,
    *,
    now: int | None = None,
) -> bool:
    current = int(time.time()) if now is None else now
    if not secret or expires < current:
        return False
    expected = sign_download(scope, resource_id, expires, secret)
    return hmac.compare_digest(expected, signature)
