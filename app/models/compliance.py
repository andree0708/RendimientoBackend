"""Consent, agent device, and audit-log models for privacy compliance."""

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UTCDateTime, generate_uuid


class ConsentRecord(TimestampMixin, Base):
    """Informed-consent record for data collection.

    Users must explicitly consent before the agent collects any metrics.
    Supports withdrawal and scope specification.
    """

    __tablename__ = "consent_records"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    granted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    scope: Mapped[str] = mapped_column(String(500), nullable=False, default="all")
    # all | activity_only | app_usage_only | minimal
    version: Mapped[str] = mapped_column(String(20), nullable=False, default="1.0")
    granted_at: Mapped[str | None] = mapped_column(UTCDateTime(timezone=True), nullable=True)
    withdrawn_at: Mapped[str | None] = mapped_column(UTCDateTime(timezone=True), nullable=True)


class AgentDevice(TimestampMixin, Base):
    """A registered local-agent installation on a worker's device."""

    __tablename__ = "agent_devices"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    device_name: Mapped[str] = mapped_column(String(255), nullable=False)
    os_type: Mapped[str] = mapped_column(String(50), nullable=False)  # windows | linux
    agent_version: Mapped[str] = mapped_column(String(20), nullable=False, default="1.0.0")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_seen_at: Mapped[str | None] = mapped_column(UTCDateTime(timezone=True), nullable=True)
    config_json: Mapped[str | None] = mapped_column(String, nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="agent_devices")


class AuditLog(TimestampMixin, Base):
    """Append-only audit trail for security-sensitive actions."""

    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    actor_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    actor_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    resource_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    detail: Mapped[str | None] = mapped_column(String(2000), nullable=True)


# Resolve forward reference
from app.models.user import User  # noqa: E402
