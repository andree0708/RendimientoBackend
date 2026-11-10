"""AI routes — model management, training, prediction, and analysis."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_pagination
from app.core.database import get_db
from app.core.deps import get_current_user, get_current_superuser
from app.core.pagination import paginate
from app.models.user import User
from app.schemas.ai import (
    FatigueAssessmentPage,
    FatigueAssessmentRead,
    ModelVersionRead,
    ModelVersionWithEval,
    PerformancePredictionPage,
    PerformancePredictionRead,
    TrainingRequest,
    TrainingResponse,
)
from app.services import ai_service, audit_service

router = APIRouter(prefix="/ai", tags=["ai"])


@router.post("/train", response_model=TrainingResponse)
async def train_model(
    data: TrainingRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_superuser),
):
    """Train or retrain a model.  Admin only."""
    result = await ai_service.train_model(db, data)
    audit_service.log_event(
        db,
        action="ai.train",
        actor_id=current_user.id,
        actor_email=current_user.email,
        resource_type="model_version",
        resource_id=result.model_version_id,
        detail=(
            f"type={data.model_type}; use_demo={data.use_demo_data}; "
            f"success={result.success}"
        ),
    )
    return result


@router.get("/models", response_model=list[ModelVersionWithEval])
def list_models(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_superuser),
):
    """List model versions.  Admin only: exposes internal artefact paths."""
    return ai_service.list_models(db)


@router.get("/models/{model_id}", response_model=ModelVersionWithEval)
def get_model(
    model_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_superuser),
):
    """Get one model version.  Admin only."""
    return ai_service.get_model(db, model_id)


@router.post("/predict/fatigue", response_model=FatigueAssessmentRead)
async def predict_fatigue(
    session_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Run a fatigue assessment for the current user."""
    return await ai_service.assess_fatigue(db, current_user.id, session_id)


@router.get("/fatigue/history", response_model=FatigueAssessmentPage)
def fatigue_history(
    pagination=Depends(get_pagination),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    assessments, total = ai_service.list_fatigue_assessments(db, current_user.id, pagination.offset, pagination.limit)
    return paginate([FatigueAssessmentRead.model_validate(a) for a in assessments], total, pagination)


@router.post("/predict/performance", response_model=PerformancePredictionRead)
async def predict_performance(
    session_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Run a performance prediction for the current user."""
    return await ai_service.predict_performance(db, current_user.id, session_id)


@router.get("/performance/history", response_model=PerformancePredictionPage)
def performance_history(
    pagination=Depends(get_pagination),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    predictions, total = ai_service.list_performance_predictions(db, current_user.id, pagination.offset, pagination.limit)
    return paginate([PerformancePredictionRead.model_validate(p) for p in predictions], total, pagination)


@router.get("/anomalies")
def detect_anomalies(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Detect anomalous patterns for the current user."""
    return ai_service.detect_anomalies(db, current_user.id)
