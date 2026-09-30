"""Time helpers shared by the data and service layers."""

from __future__ import annotations

from datetime import UTC, datetime


def to_utc(value: datetime) -> datetime:
    """Return ``value`` as an aware UTC datetime; naive values are taken to be UTC (D7)."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
