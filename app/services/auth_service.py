"""Authentication service: registration, login, token refresh."""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, UnauthorizedError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.compliance import ConsentRecord
from app.models.user import Role, User
from app.schemas.auth import LoginRequest, RegisterRequest


def register(db: Session, data: RegisterRequest) -> tuple[User, str, str]:
    """Create a new user account and return (user, access_token, refresh_token)."""
    existing = db.query(User).filter(User.email == data.email).first()
    if existing:
        raise ConflictError("An account with that email already exists")

    user = User(
        email=data.email,
        full_name=data.full_name,
        hashed_password=hash_password(data.password),
        preferred_scale_max=5,
    )
    db.add(user)
    db.flush()  # Assigns user.id without committing

    # Assign default "worker" role
    worker_role = db.query(Role).filter(Role.name == "worker").first()
    if worker_role is None:
        worker_role = Role(name="worker", description="Standard worker role")
        db.add(worker_role)
        db.flush()
    user.roles.append(worker_role)

    # Create a default consent record (not granted until user accepts)
    consent = ConsentRecord(user_id=user.id, granted=False, scope="all", version="1.0")
    db.add(consent)

    db.commit()
    db.refresh(user)

    access = create_access_token(user.id, extra_claims={"email": user.email})
    refresh = create_refresh_token(user.id, extra_claims={"email": user.email})
    return user, access, refresh


def login(db: Session, data: LoginRequest) -> tuple[User, str, str]:
    """Authenticate a user and return (user, access_token, refresh_token)."""
    user = db.query(User).filter(User.email == data.email).first()
    if not user or not verify_password(data.password, user.hashed_password):
        raise UnauthorizedError("Incorrect email or password")
    if not user.is_active:
        raise UnauthorizedError("Account is inactive")

    access = create_access_token(user.id, extra_claims={"email": user.email})
    refresh = create_refresh_token(user.id, extra_claims={"email": user.email})
    return user, access, refresh


def refresh_access_token(db: Session, refresh_token: str) -> tuple[User, str]:
    """Validate a refresh token and issue a new access token."""
    payload = decode_token(refresh_token)
    if payload is None or payload.get("type") != "refresh":
        raise UnauthorizedError("Invalid refresh token")

    user_id = payload.get("sub")
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_active:
        raise UnauthorizedError("Invalid refresh token")

    access = create_access_token(user.id, extra_claims={"email": user.email})
    return user, access
