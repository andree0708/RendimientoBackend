"""User management service."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.models.user import User
from app.schemas.user import UserUpdate


def get_user(db: Session, user_id: str) -> User:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise NotFoundError("User not found")
    return user


def update_user(db: Session, user_id: str, data: UserUpdate) -> User:
    user = get_user(db, user_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(user, field, value)
    db.commit()
    db.refresh(user)
    return user


def delete_user(db: Session, user_id: str) -> None:
    user = get_user(db, user_id)
    user.is_active = False
    db.commit()


def list_users(db: Session, offset: int = 0, limit: int = 20) -> tuple[list[User], int]:
    query = db.query(User).filter(User.is_active.is_(True))
    total = query.count()
    users = query.offset(offset).limit(limit).all()
    return users, total
