"""User management routes."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_pagination
from app.core.database import get_db
from app.core.deps import get_current_user, get_current_superuser
from app.core.pagination import paginate
from app.models.user import User
from app.schemas.user import UserPage, UserRead, UserUpdate
from app.services import user_service

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserRead)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.patch("/me", response_model=UserRead)
def update_me(
    data: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return user_service.update_user(db, current_user.id, data)


@router.get("", response_model=UserPage, dependencies=[Depends(get_current_superuser)])
def list_users(
    pagination=Depends(get_pagination),
    db: Session = Depends(get_db),
):
    users, total = user_service.list_users(db, pagination.offset, pagination.limit)
    return paginate([UserRead.model_validate(u) for u in users], total, pagination)


@router.get("/{user_id}", response_model=UserRead)
def get_user(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if user_id != current_user.id and not current_user.is_superuser:
        from app.core.exceptions import ForbiddenError

        raise ForbiddenError("You can only view your own profile")
    return user_service.get_user(db, user_id)
