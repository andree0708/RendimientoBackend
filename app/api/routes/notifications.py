"""Notification routes."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_pagination
from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.pagination import paginate
from app.models.user import User
from app.schemas.notification import NotificationPage, NotificationRead
from app.services import notification_service

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=NotificationPage)
async def list_notifications(
    pagination=Depends(get_pagination),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    notifs, total = notification_service.list_notifications(db, current_user.id, pagination.offset, pagination.limit)
    return paginate([NotificationRead.model_validate(n) for n in notifs], total, pagination)


@router.post("/{notification_id}/read", response_model=NotificationRead | None)
async def mark_notification_read(
    notification_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await notification_service.mark_read(db, current_user.id, notification_id)
