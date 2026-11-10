"""Recommendation schemas."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import Page


class RecommendationRead(BaseModel):
    id: str
    user_id: str
    session_id: str | None = None
    generated_at: datetime
    category: str
    title: str
    body: str
    reason: str | None = None
    status: str
    priority: str
    created_at: datetime

    model_config = {"from_attributes": True}


class RecommendationUpdate(BaseModel):
    status: str | None = Field(default=None, max_length=20)
    # pending | accepted | dismissed | completed


class RecommendationPage(Page):
    items: list[RecommendationRead]
