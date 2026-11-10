"""User schemas."""

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.schemas.common import Page
from app.schemas.password_policy import validate_strong_password


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    full_name: str = Field(min_length=1, max_length=255)
    preferred_scale_max: int = Field(default=5, ge=3, le=10)

    @field_validator("password", mode="after")
    @classmethod
    def _strong_password(cls, v: str) -> str:
        return validate_strong_password(v)


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, max_length=255)
    avatar_url: str | None = Field(default=None, max_length=512)
    preferred_scale_max: int | None = Field(default=None, ge=3, le=10)
    is_active: bool | None = None


class UserRead(BaseModel):
    id: str
    email: EmailStr
    full_name: str
    is_active: bool
    is_superuser: bool
    avatar_url: str | None = None
    preferred_scale_max: int
    organization_id: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class UserPage(Page):
    items: list[UserRead]
