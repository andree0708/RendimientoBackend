"""Notification schemas."""

from datetime import datetime

from pydantic import BaseModel

from app.schemas.common import Page


class NotificationRead(BaseModel):
    id: str
    user_id: str
    notification_type: str
    title: str
    message: str
    payload: str | None = None
    is_read: bool
    read_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class NotificationPage(Page):
    items: list[NotificationRead]
