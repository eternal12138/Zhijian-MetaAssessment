"""Time helpers for the system-wide UTC timestamp contract."""
from __future__ import annotations

from datetime import datetime, timezone


UTC = timezone.utc


def utc_now_naive() -> datetime:
    """Return the current UTC instant for storage in MySQL DATETIME columns."""
    return datetime.now(UTC).replace(tzinfo=None)


def as_utc(value: datetime) -> datetime:
    """Interpret a naive database datetime as UTC and return an aware value."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def utc_isoformat(value: datetime | None) -> str:
    """Serialize a stored UTC datetime with an explicit ``Z`` suffix."""
    if value is None:
        return ""
    return as_utc(value).isoformat().replace("+00:00", "Z")
