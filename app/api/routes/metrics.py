"""Metrics routes — agent ingestion and historical queries."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_pagination
from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.pagination import paginate
from app.models.user import User
from app.schemas.metrics import ActivityMetricBatch, ActivityMetricPage, ActivityMetricRead
from app.services import metrics_service
from app.websocket.manager import ws_manager

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.post("/batch", response_model=list[ActivityMetricRead], status_code=201)
async def ingest_metrics(
    batch: ActivityMetricBatch,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    metrics = metrics_service.ingest_batch(db, current_user.id, batch)
    await ws_manager.send_to_user(
        current_user.id,
        "metrics.batch_received",
        {
            "session_id": batch.session_id,
            "count": len(metrics),
        },
        session_id=batch.session_id,
    )
    return metrics


@router.get("/session/{session_id}", response_model=ActivityMetricPage)
def list_session_metrics(
    session_id: str,
    pagination=Depends(get_pagination),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    metrics, total = metrics_service.list_metrics(
        db, session_id, current_user.id, pagination.offset, pagination.limit
    )
    return paginate([ActivityMetricRead.model_validate(m) for m in metrics], total, pagination)
