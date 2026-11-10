"""Shared mixins for ORM models."""

import uuid

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column


class TimestampMixin:
    """Adds ``created_at`` and ``updated_at`` columns to a model."""

    created_at: Mapped[str] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[str] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


def generate_uuid() -> str:
    """Return a UUID4 hex string for use as a default primary key."""
    return uuid.uuid4().hex
