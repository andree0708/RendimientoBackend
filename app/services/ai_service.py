"""AI service — thin wrapper that connects the pipeline to the API layer."""

from sqlalchemy.orm import Session

from app.ai import pipeline
from app.models.ai import (
    FatigueAssessment,
    ModelVersion,
    PerformancePrediction,
)
from app.schemas.ai import (
    ModelVersionWithEval,
    TrainingRequest,
    TrainingResponse,
)


async def train_model(db: Session, request: TrainingRequest) -> TrainingResponse:
    """Train or retrain a model via the pipeline."""
    try:
        result = await pipeline.train_pipeline(
            db, request.model_type, request.user_id, request.use_demo_data
        )
        return TrainingResponse(
            success=True,
            model_version_id=result["model_version_id"],
            message=f"Model trained: {result['model_type']} ({result['algorithm']})",
            metrics=result["metrics"],
        )
    except Exception as exc:
        return TrainingResponse(success=False, message=str(exc), metrics=None)


def list_models(db: Session) -> list[ModelVersionWithEval]:
    """List all model versions with their evaluations."""
    versions = db.query(ModelVersion).order_by(ModelVersion.trained_on.desc()).all()
    result = []
    for v in versions:
        data = ModelVersionWithEval.model_validate(v)
        result.append(data)
    return result


def get_model(db: Session, model_id: str) -> ModelVersionWithEval:
    mv = db.query(ModelVersion).filter(ModelVersion.id == model_id).first()
    if not mv:
        from app.core.exceptions import NotFoundError

        raise NotFoundError("Model not found")
    return ModelVersionWithEval.model_validate(mv)


async def assess_fatigue(db: Session, user_id: str, session_id: str | None) -> FatigueAssessment:
    return await pipeline.assess_fatigue(db, user_id, session_id)


def list_fatigue_assessments(db: Session, user_id: str, offset: int, limit: int):
    q = db.query(FatigueAssessment).filter(FatigueAssessment.user_id == user_id).order_by(
        FatigueAssessment.assessed_at.desc()
    )
    total = q.count()
    return q.offset(offset).limit(limit).all(), total


async def predict_performance(db: Session, user_id: str, session_id: str | None) -> PerformancePrediction:
    return await pipeline.predict_performance(db, user_id, session_id)


def list_performance_predictions(db: Session, user_id: str, offset: int, limit: int):
    q = db.query(PerformancePrediction).filter(PerformancePrediction.user_id == user_id).order_by(
        PerformancePrediction.predicted_at.desc()
    )
    total = q.count()
    return q.offset(offset).limit(limit).all(), total


def detect_anomalies(db: Session, user_id: str) -> dict:
    return pipeline.detect_anomalies(db, user_id)
