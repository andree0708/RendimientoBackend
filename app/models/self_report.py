"""Self-report model for worker-perceived fatigue, stress, and effort."""

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, generate_uuid


class SelfReport(TimestampMixin, Base):
    """Periodic self-reported wellness indicators.

    Scales default to 1-5 but can be configured per user
    (``User.preferred_scale_max``).  These reports serve as the reference
    labels for the fatigue-estimation model and complement the objective
    metrics collected by the agent.
    """

    __tablename__ = "self_reports"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("work_sessions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    reported_at: Mapped[str] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    # Perceived indicators (1 to scale_max, typically 1-5)
    fatigue_level: Mapped[int] = mapped_column(Integer, nullable=False)
    stress_level: Mapped[int] = mapped_column(Integer, nullable=False)
    concentration_level: Mapped[int] = mapped_column(Integer, nullable=False)
    task_difficulty: Mapped[int] = mapped_column(Integer, nullable=False)
    perceived_effort: Mapped[int] = mapped_column(Integer, nullable=False)
    need_for_break: Mapped[int] = mapped_column(Integer, nullable=False)

    # Rest quality
    sleep_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    sleep_quality: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rest_quality_previous_night: Mapped[int | None] = mapped_column(Integer, nullable=True)

    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Synthetic seed/demo rows. Excluded from ML training (see pipeline).
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    user: Mapped["User"] = relationship("User", back_populates="self_reports")
    session: Mapped["WorkSession | None"] = relationship("WorkSession", back_populates="self_reports")


# Resolve forward references
from app.models.user import User  # noqa: E402
from app.models.session import WorkSession  # noqa: E402
