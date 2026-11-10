"""Task schemas."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import Page


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=2000)
    estimated_seconds: int = Field(default=0, ge=0)
    complexity: int = Field(default=3, ge=1, le=5)
    session_id: str | None = None


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None, max_length=2000)
    estimated_seconds: int | None = Field(default=None, ge=0)
    complexity: int | None = Field(default=None, ge=1, le=5)
    status: str | None = Field(default=None, max_length=20)
    actual_seconds: int | None = Field(default=None, ge=0)
    completed_at: datetime | None = None


class TaskResultRead(BaseModel):
    id: str
    task_id: str
    outcome: str
    errors_count: int
    quality_rating: int | None = None
    notes: str | None = None
    deviation_seconds: int
    created_at: datetime

    model_config = {"from_attributes": True}


class TaskRead(BaseModel):
    id: str
    user_id: str
    session_id: str | None = None
    title: str
    description: str | None = None
    estimated_seconds: int
    actual_seconds: int
    complexity: int
    status: str
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    results: list[TaskResultRead] = []

    model_config = {"from_attributes": True}


class TaskPage(Page):
    items: list[TaskRead]


class TaskResultCreate(BaseModel):
    outcome: str = Field(default="completed", max_length=20)
    errors_count: int = Field(default=0, ge=0)
    quality_rating: int | None = Field(default=None, ge=1, le=5)
    notes: str | None = Field(default=None, max_length=1000)
