"""AI model registry and prediction/assessment models."""

from sqlalchemy import Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UTCDateTime, generate_uuid


class FatigueAssessment(TimestampMixin, Base):
    """Result of a fatigue-estimation run for a user/session.

    Derived from the fatigue classification model.  This is an estimate of
    operational signals related to perceived fatigue — NOT a medical diagnosis.
    """

    __tablename__ = "fatigue_assessments"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("work_sessions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    assessed_at: Mapped[str] = mapped_column(UTCDateTime(timezone=True), nullable=False, index=True)

    # Risk category: low | moderate | high
    risk_category: Mapped[str] = mapped_column(String(20), nullable=False)
    # Probability of the positive (fatigue) class
    risk_probability: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Top contributing features (JSON string)
    top_features: Mapped[str | None] = mapped_column(String, nullable=True)
    comparison_to_baseline: Mapped[str | None] = mapped_column(String, nullable=True)

    model_version_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("model_versions.id", ondelete="SET NULL"), nullable=True
    )

    model_version: Mapped["ModelVersion | None"] = relationship("ModelVersion")


class PerformancePrediction(TimestampMixin, Base):
    """Prediction of a possible performance decrease in a future window.

    The horizon is configurable (default 30 min).  Labels are built from
    task-completion and error-rate trends, not from fatigue reports.
    """

    __tablename__ = "performance_predictions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("work_sessions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    predicted_at: Mapped[str] = mapped_column(UTCDateTime(timezone=True), nullable=False, index=True)
    target_time: Mapped[str] = mapped_column(UTCDateTime(timezone=True), nullable=False)

    # Regression target: estimated performance variation (-1.0 to 1.0)
    predicted_variation: Mapped[float] = mapped_column(Float, nullable=False)
    # Classification companion: low_risk | moderate_risk | high_risk
    risk_label: Mapped[str] = mapped_column(String(20), nullable=False)

    horizon_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    top_features: Mapped[str | None] = mapped_column(String, nullable=True)

    model_version_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("model_versions.id", ondelete="SET NULL"), nullable=True
    )

    model_version: Mapped["ModelVersion | None"] = relationship("ModelVersion")


class ModelVersion(TimestampMixin, Base):
    """Registry of trained ML model artefacts and their metadata."""

    __tablename__ = "model_versions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    # fatigue_classification | performance_regression | anomaly_detection | clustering
    model_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    algorithm: Mapped[str] = mapped_column(String(100), nullable=False)
    version_tag: Mapped[str] = mapped_column(String(50), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=False)
    trained_on: Mapped[str] = mapped_column(UTCDateTime(timezone=True), nullable=False)
    samples_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    evaluations: Mapped[list["ModelEvaluation"]] = relationship(
        "ModelEvaluation", back_populates="model_version"
    )


class ModelEvaluation(TimestampMixin, Base):
    """Evaluation metrics for a specific model version."""

    __tablename__ = "model_evaluations"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    model_version_id: Mapped[str] = mapped_column(
        String, ForeignKey("model_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Classification metrics (nullable for regression models)
    precision: Mapped[float | None] = mapped_column(Float, nullable=True)
    recall: Mapped[float | None] = mapped_column(Float, nullable=True)
    f1_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    roc_auc: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Regression metrics (nullable for classification models)
    mae: Mapped[float | None] = mapped_column(Float, nullable=True)
    rmse: Mapped[float | None] = mapped_column(Float, nullable=True)
    r2: Mapped[float | None] = mapped_column(Float, nullable=True)
    confusion_matrix: Mapped[str | None] = mapped_column(String, nullable=True)

    model_version: Mapped[ModelVersion] = relationship("ModelVersion", back_populates="evaluations")
