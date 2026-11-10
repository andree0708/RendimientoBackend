"""Self-report schemas."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import Page


class SelfReportCreate(BaseModel):
    fatigue_level: int = Field(ge=1, le=10)
    stress_level: int = Field(ge=1, le=10)
    concentration_level: int = Field(ge=1, le=10)
    task_difficulty: int = Field(ge=1, le=10)
    perceived_effort: int = Field(ge=1, le=10)
    need_for_break: int = Field(ge=1, le=10)
    sleep_hours: float | None = Field(default=None, ge=0, le=24)
    sleep_quality: int | None = Field(default=None, ge=1, le=10)
    rest_quality_previous_night: int | None = Field(default=None, ge=1, le=10)
    notes: str | None = Field(default=None, max_length=500)
    session_id: str | None = None


class SelfReportRead(BaseModel):
    id: str
    user_id: str
    session_id: str | None = None
    reported_at: datetime
    fatigue_level: int
    stress_level: int
    concentration_level: int
    task_difficulty: int
    perceived_effort: int
    need_for_break: int
    sleep_hours: float | None = None
    sleep_quality: int | None = None
    rest_quality_previous_night: int | None = None
    notes: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class SelfReportPage(Page):
    items: list[SelfReportRead]
