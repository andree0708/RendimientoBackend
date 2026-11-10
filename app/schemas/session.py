"""Work session schemas."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import Page


class WorkSessionCreate(BaseModel):
    notes: str | None = Field(default=None, max_length=500)


class WorkSessionUpdate(BaseModel):
    ended_at: datetime | None = None
    status: str | None = Field(default=None, max_length=20)
    notes: str | None = Field(default=None, max_length=500)


class WorkSessionRead(BaseModel):
    id: str
    user_id: str
    started_at: datetime
    ended_at: datetime | None = None
    total_active_seconds: int
    total_idle_seconds: int
    total_pause_seconds: int
    pause_count: int
    status: str
    notes: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class WorkSessionPage(Page):
    items: list[WorkSessionRead]
