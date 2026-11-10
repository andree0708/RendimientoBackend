"""AI model, prediction, and training schemas."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import Page


class FatigueAssessmentRead(BaseModel):
    id: str
    user_id: str
    session_id: str | None = None
    assessed_at: datetime
    risk_category: str
    risk_probability: float
    confidence: float | None = None
    top_features: str | None = None
    comparison_to_baseline: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class FatigueAssessmentPage(Page):
    items: list[FatigueAssessmentRead]


class PerformancePredictionRead(BaseModel):
    id: str
    user_id: str
    session_id: str | None = None
    predicted_at: datetime
    target_time: datetime
    predicted_variation: float
    risk_label: str
    horizon_minutes: int
    confidence: float | None = None
    top_features: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class PerformancePredictionPage(Page):
    items: list[PerformancePredictionRead]


class ModelVersionRead(BaseModel):
    id: str
    name: str
    model_type: str
    algorithm: str
    version_tag: str
    file_path: str
    is_active: bool
    trained_on: datetime
    samples_used: int
    notes: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ModelEvaluationRead(BaseModel):
    id: str
    model_version_id: str
    precision: float | None = None
    recall: float | None = None
    f1_score: float | None = None
    roc_auc: float | None = None
    mae: float | None = None
    rmse: float | None = None
    r2: float | None = None
    confusion_matrix: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ModelVersionWithEval(ModelVersionRead):
    evaluations: list[ModelEvaluationRead] = []


class TrainingRequest(BaseModel):
    """Request to train or retrain a model."""

    model_type: str = Field(
        description="fatigue_classification | performance_regression | anomaly_detection"
    )
    use_demo_data: bool = True
    user_id: str | None = None  # If None, trains on all users


class TrainingResponse(BaseModel):
    success: bool
    model_version_id: str | None = None
    message: str
    metrics: dict | None = None
