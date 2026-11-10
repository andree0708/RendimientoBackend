"""Recommendation routes."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_pagination
from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.pagination import paginate
from app.models.user import User
from app.schemas.recommendation import RecommendationPage, RecommendationRead, RecommendationUpdate
from app.services import recommendation_service

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


@router.get("", response_model=RecommendationPage)
def list_recommendations(
    status: str | None = Query(default=None),
    pagination=Depends(get_pagination),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    recs, total = recommendation_service.list_recommendations(
        db, current_user.id, status, pagination.offset, pagination.limit
    )
    return paginate([RecommendationRead.model_validate(r) for r in recs], total, pagination)


@router.patch("/{rec_id}", response_model=RecommendationRead)
def update_recommendation(
    rec_id: str,
    data: RecommendationUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return recommendation_service.update_recommendation(db, rec_id, current_user.id, data)
