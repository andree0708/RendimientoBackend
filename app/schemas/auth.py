"""Authentication schemas."""

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.schemas.password_policy import validate_strong_password


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TokenPayload(BaseModel):
    sub: str
    type: str
    exp: int


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=255)

    @field_validator("password", mode="after")
    @classmethod
    def _strong_password(cls, v: str) -> str:
        return validate_strong_password(v)


class RefreshRequest(BaseModel):
    refresh_token: str
