"""Notification service — persist notifications and push via WebSocket."""

import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.notification import Notification
from app.websocket.manager import ws_manager


async def create_and_push(
    db: Session,
    user_id: str,
    notification_type: str,
    title: str,
    message: str,
    payload: dict | None = None,
) -> Notification:
    """Persist a notification and push it over WebSocket if the user is connected."""
    notif = Notification(
        user_id=user_id,
        notification_type=notification_type,
        title=title,
        message=message,
        payload=json.dumps(payload or {}),
        is_read=False,
    )
    db.add(notif)
    db.commit()
    db.refresh(notif)

    # Push to live connection (best-effort; no error if disconnected)
    if ws_manager.is_connected(user_id):
        await ws_manager.send_to_user(
            user_id=user_id,
            event_type="notification.created",
            payload={
                "notification_id": notif.id,
                "notification_type": notification_type,
                "title": title,
                "message": message,
                **(payload or {}),
            },
        )

    return notif


def list_notifications(
    db: Session, user_id: str, offset: int = 0, limit: int = 30
) -> tuple[list[Notification], int]:
    query = (
        db.query(Notification)
        .filter(Notification.user_id == user_id)
        .order_by(Notification.created_at.desc())
    )
    total = query.count()
    return query.offset(offset).limit(limit).all(), total


async def mark_read(db: Session, user_id: str, notification_id: str) -> Notification | None:
    notif = (
        db.query(Notification)
        .filter(Notification.id == notification_id, Notification.user_id == user_id)
        .first()
    )
    if notif:
        notif.is_read = True
        notif.read_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(notif)
        await ws_manager.send_to_user(user_id, "notification.read", {"notification_id": notification_id})
    return notif
