"""Organization schemas."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import Page


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=500)


class OrganizationRead(BaseModel):
    id: str
    name: str
    description: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class OrganizationPage(Page):
    items: list[OrganizationRead]
