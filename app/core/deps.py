"""FastAPI dependencies for authentication and authorization."""

from fastapi import Depends, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.security import decode_token
from app.models.user import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Validate the JWT and return the current user."""
    credentials_error = UnauthorizedError("Invalid or expired credentials")
    payload = decode_token(token)
    if payload is None or payload.get("type") != "access":
        raise credentials_error

    user_id = payload.get("sub")
    if not user_id:
        raise credentials_error

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise credentials_error
    if not user.is_active:
        raise UnauthorizedError("Account is inactive")
    return user


def get_current_superuser(
    current_user: User = Depends(get_current_user),
) -> User:
    """Require the current user to be a superuser (admin)."""
    if not current_user.is_superuser:
        raise ForbiddenError("Administrator privileges required")
    return current_user


def get_current_user_optional(
    token: str | None = Depends(OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)),
    db: Session = Depends(get_db),
) -> User | None:
    """Return the current user if authenticated, otherwise None."""
    if not token:
        return None
    payload = decode_token(token)
    if payload is None or payload.get("type") != "access":
        return None
    user_id = payload.get("sub")
    if not user_id:
        return None
    return db.query(User).filter(User.id == user_id).first()
