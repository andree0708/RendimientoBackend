"""Administration routes — aggregated, anonymized team/org statistics."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_superuser
from app.models.user import User
from app.services import admin_service

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
