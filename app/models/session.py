"""Work session and activity-metric models."""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, generate_uuid


class ApplicationCategory(TimestampMixin, Base):
    """Catalogue of application categories (e.g. IDE, Browser, Communication)."""

    __tablename__ = "application_categories"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)


class WorkSession(TimestampMixin, Base):
    """A single work session for a user (start/stop controlled by the agent)."""

    __tablename__ = "work_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    total_active_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_idle_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_pause_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    pause_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="work_sessions")
    metrics: Mapped[list["ActivityMetric"]] = relationship(
        "ActivityMetric", back_populates="session", cascade="all, delete-orphan"
    )
    tasks: Mapped[list["Task"]] = relationship("Task", back_populates="session")
    self_reports: Mapped[list["SelfReport"]] = relationship("SelfReport", back_populates="session")


class ActivityMetric(TimestampMixin, Base):
    """Aggregated activity metrics collected by the local agent.

    Privacy-first: only aggregated metadata is stored, never keystrokes,
    screenshots, content, or browsing history.
    """

    __tablename__ = "activity_metrics"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    session_id: Mapped[str] = mapped_column(
        String, ForeignKey("work_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Time window this metric batch covers
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    interval_seconds: Mapped[int] = mapped_column(Integer, default=60, nullable=False)

    # General activity
    active_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    idle_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    continuous_work_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    pause_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    pause_total_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Application usage (aggregated by category, never content)
    app_switch_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    interruptions_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    app_category_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("application_categories.id", ondelete="SET NULL"), nullable=True
    )
    app_category_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Task indicators (from explicit records, not assumed productivity)
    tasks_started: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tasks_completed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    errors_reported: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Raw JSON blob for flexible extra data (never sensitive content)
    extra_metadata: Mapped[str | None] = mapped_column(String, nullable=True)

    session: Mapped[WorkSession] = relationship("WorkSession", back_populates="metrics")


# Resolve forward references
from app.models.user import User  # noqa: E402
from app.models.task import Task  # noqa: E402
from app.models.self_report import SelfReport  # noqa: E402
