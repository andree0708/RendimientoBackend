"""Consent schemas."""

from datetime import datetime

from pydantic import BaseModel, Field


class ConsentRead(BaseModel):
    granted: bool
    scope: str
    version: str
    granted_at: datetime | None = None
    withdrawn_at: datetime | None = None

    model_config = {"from_attributes": True}


class ConsentUpdate(BaseModel):
    granted: bool
    scope: str = Field(default="all", max_length=50, pattern="^(all|activity_only|app_usage_only|minimal)$")
