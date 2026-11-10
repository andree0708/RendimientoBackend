"""Activity metric schemas."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import Page


class ActivityMetricRead(BaseModel):
    id: str
    session_id: str
    user_id: str
    recorded_at: datetime
    interval_seconds: int
    active_seconds: int
    idle_seconds: int
    continuous_work_seconds: int
    pause_count: int
    pause_total_seconds: int
    app_switch_count: int
    interruptions_count: int
    app_category_seconds: int
    tasks_started: int
    tasks_completed: int
    errors_reported: int

    model_config = {"from_attributes": True}


class ActivityMetricItem(BaseModel):
    """A single metric reading sent by the local agent."""

    recorded_at: datetime
    interval_seconds: int = Field(default=60, ge=1)
    active_seconds: int = Field(default=0, ge=0)
    idle_seconds: int = Field(default=0, ge=0)
    continuous_work_seconds: int = Field(default=0, ge=0)
    pause_count: int = Field(default=0, ge=0)
    pause_total_seconds: int = Field(default=0, ge=0)
    app_switch_count: int = Field(default=0, ge=0)
    interruptions_count: int = Field(default=0, ge=0)
    app_category_id: str | None = None
    app_category_seconds: int = Field(default=0, ge=0)
    tasks_started: int = Field(default=0, ge=0)
    tasks_completed: int = Field(default=0, ge=0)
    errors_reported: int = Field(default=0, ge=0)


class ActivityMetricBatch(BaseModel):
    """Batch of metrics sent by the agent for a given session."""

    session_id: str
    metrics: list[ActivityMetricItem]


class ActivityMetricPage(Page):
    items: list[ActivityMetricRead]
