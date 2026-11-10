"""Task and task-result models."""

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, generate_uuid


class Task(TimestampMixin, Base):
    """A task registered by the user with estimated and actual durations."""

    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("work_sessions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(String(2000), nullable=True)

    estimated_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    actual_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    complexity: Mapped[int] = mapped_column(Integer, nullable=False, default=3)  # 1-5 scale
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    # pending | in_progress | completed | cancelled

    started_at: Mapped[str | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[str | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="tasks")
    session: Mapped["WorkSession | None"] = relationship("WorkSession", back_populates="tasks")
    results: Mapped[list["TaskResult"]] = relationship(
        "TaskResult", back_populates="task", cascade="all, delete-orphan"
    )


class TaskResult(TimestampMixin, Base):
    """Result of a completed task (errors, quality self-assessment)."""

    __tablename__ = "task_results"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    task_id: Mapped[str] = mapped_column(
        String, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    outcome: Mapped[str] = mapped_column(String(20), nullable=False, default="completed")
    errors_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quality_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1-5
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    deviation_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # actual - estimated; positive means it took longer

    task: Mapped[Task] = relationship("Task", back_populates="results")


# Resolve forward references
from app.models.user import User  # noqa: E402
from app.models.session import WorkSession  # noqa: E402
