"""Custom column types."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator


def to_utc(value: datetime) -> datetime:
    """Return ``value`` as an aware UTC datetime; naive values are taken to be UTC (D7)."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class UTCDateTime(TypeDecorator[datetime]):
    """A timestamp that is always stored in UTC and always read back as aware UTC.

    PostgreSQL stores it as ``TIMESTAMP WITH TIME ZONE``. SQLite has no time zone
    support, so the value is stored as naive UTC text in one fixed format; that
    keeps comparisons such as the ``end_date >= start_date`` CHECK correct.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        value = to_utc(value)
        if dialect.name == "sqlite":
            return value.replace(tzinfo=None)
        return value

    def process_result_value(self, value: Any, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        return to_utc(value)
