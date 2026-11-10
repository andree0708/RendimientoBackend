"""Refresh-token revocation for rotation."""

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, generate_uuid


class RevokedRefreshToken(TimestampMixin, Base):
    """A used/invalidated refresh-token jti (single-use rotation)."""

    __tablename__ = "revoked_refresh_tokens"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    jti: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
