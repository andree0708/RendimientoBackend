"""Administration routes — aggregated, anonymized team/org statistics."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_superuser
from app.models.user import User
from app.services import admin_service, audit_service, privacy_service

router = APIRouter(prefix="/admin", tags=["administration"])


@router.get("/stats", dependencies=[Depends(get_current_superuser)])
def get_aggregate_stats(db: Session = Depends(get_db)):
    """Aggregated, anonymized organizational statistics (no individual data)."""
    return admin_service.get_aggregate_stats(db)


@router.get("/audit-logs", dependencies=[Depends(get_current_superuser)])
def get_audit_logs(
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """Query the audit log.  Admin only."""
    return admin_service.get_audit_logs(db, skip, limit)


@router.get("/models", dependencies=[Depends(get_current_superuser)])
def list_all_models(db: Session = Depends(get_db)):
    """List all AI model versions.  Admin only."""
    from app.services import ai_service
    return ai_service.list_models(db)


@router.post("/purge")
def purge_old_data(
    retention_days: int | None = Query(default=None, ge=1, le=3650),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_superuser),
):
    """Delete activity metrics older than the retention window. Admin only."""
    deleted = privacy_service.purge_old_metrics(db, retention_days)
    audit_service.log_event(
        db,
        action="privacy.purge",
        actor_id=current_user.id,
        actor_email=current_user.email,
        resource_type="activity_metrics",
        detail=f"deleted={deleted}; retention_days={retention_days}",
    )
    return {"deleted_metrics": deleted}
