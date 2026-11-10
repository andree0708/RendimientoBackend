"""Authentication routes: register, login, refresh."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.auth import LoginRequest, RefreshRequest, RegisterRequest, Token
from app.schemas.user import UserRead
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=Token, status_code=201)
def register(data: RegisterRequest, db: Session = Depends(get_db)):
    user, access, refresh = auth_service.register(db, data)
    return Token(access_token=access, refresh_token=refresh)


@router.post("/login", response_model=Token)
def login(data: LoginRequest, db: Session = Depends(get_db)):
    user, access, refresh = auth_service.login(db, data)
    return Token(access_token=access, refresh_token=refresh)


@router.post("/refresh", response_model=dict)
def refresh(data: RefreshRequest, db: Session = Depends(get_db)):
    user, access, new_refresh = auth_service.refresh_access_token(db, data.refresh_token)
    return {
        "access_token": access,
        "refresh_token": new_refresh,
        "token_type": "bearer",
    }


class LogoutRequest(RefreshRequest):
    pass


@router.post("/logout")
def logout(
    data: RefreshRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Revoke one refresh token (logout on one device)."""
    revoked = auth_service.logout(db, data.refresh_token)
    return {"revoked": revoked}


@router.post("/logout-all")
def logout_all(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Revoke all refresh tokens (force re-login everywhere)."""
    version = auth_service.logout_all(db, current_user)
    return {"token_version": version}


@router.get("/me", response_model=UserRead)
def me(current_user: User = Depends(get_current_user)):
    return current_user
