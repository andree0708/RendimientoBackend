"""Team schemas."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import Page


class TeamCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=500)
    organization_id: str


class TeamRead(BaseModel):
    id: str
    name: str
    description: str | None = None
    organization_id: str
    created_at: datetime

    model_config = {"from_attributes": True}


class TeamPage(Page):
    items: list[TeamRead]
