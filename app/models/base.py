"""Shared mixins and column types for ORM models."""

import uuid
from datetime import timezone

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator):
    """DateTime that always comes back timezone-aware (UTC).

    SQLite drops timezone info on storage, so naive datetimes read back
    from the DB would be misinterpreted as local time by clients (e.g. a
    session starting "in the future", producing negative durations).
    This type re-attaches UTC on load; PostgreSQL already returns aware
    values and is left untouched. Storage format is unchanged, so no
    migration is needed.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


class TimestampMixin:
    """Adds ``created_at`` and ``updated_at`` columns to a model."""

    created_at: Mapped[str] = mapped_column(
        UTCDateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[str] = mapped_column(
        UTCDateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


def generate_uuid() -> str:
    """Return a UUID4 hex string for use as a default primary key."""
    return uuid.uuid4().hex
