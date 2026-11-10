"""Shared API dependencies and helpers."""

from fastapi import Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.services import audit_service

# Re-export for convenience
from app.core.deps import get_current_superuser  # noqa: F401


def get_pagination(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    from app.core.pagination import PaginationParams

    return PaginationParams(page=page, page_size=page_size)


def audit_action(action: str):
    """Decorator-like helper: call inside endpoints to log audit events."""

    def _log(db: Session, user: User, resource_type: str | None = None, resource_id: str | None = None, detail: str | None = None):
        audit_service.log_event(
            db=db,
            action=action,
            actor_id=user.id,
            actor_email=user.email,
            resource_type=resource_type,
            resource_id=resource_id,
            detail=detail,
        )

    return _log
