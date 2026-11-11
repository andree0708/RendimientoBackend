"""Work session service: start, stop, list, aggregate."""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError
from app.models.session import WorkSession
from app.models.user import User
from app.schemas.session import WorkSessionUpdate


def start_session(db: Session, user: User, notes: str | None = None) -> WorkSession:
    """Start a new work session for the user."""
    # Prevent multiple active sessions
    active = (
        db.query(WorkSession)
        .filter(WorkSession.user_id == user.id, WorkSession.status == "active")
        .first()
    )
    if active:
        raise ConflictError("Ya tienes una sesión de trabajo activa")

    session = WorkSession(
        user_id=user.id,
        started_at=datetime.now(timezone.utc),
        status="active",
        notes=notes,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def stop_session(db: Session, session_id: str, user_id: str) -> WorkSession:
    """End an active work session."""
    session = (
        db.query(WorkSession)
        .filter(WorkSession.id == session_id, WorkSession.user_id == user_id)
        .first()
    )
    if not session:
        raise NotFoundError("Sesión de trabajo no encontrada")
    if session.status != "active":
        raise ConflictError("La sesión ya terminó")

    session.ended_at = datetime.now(timezone.utc)
    session.status = "completed"
    db.commit()
    db.refresh(session)
    return session


def get_session(db: Session, session_id: str, user_id: str) -> WorkSession:
    session = (
        db.query(WorkSession)
        .filter(WorkSession.id == session_id, WorkSession.user_id == user_id)
        .first()
    )
    if not session:
        raise NotFoundError("Sesión de trabajo no encontrada")
    return session


def get_active_session(db: Session, user_id: str) -> WorkSession | None:
    return (
        db.query(WorkSession)
        .filter(WorkSession.user_id == user_id, WorkSession.status == "active")
        .first()
    )


def list_sessions(
    db: Session,
    user_id: str,
    offset: int = 0,
    limit: int = 20,
) -> tuple[list[WorkSession], int]:
    query = db.query(WorkSession).filter(WorkSession.user_id == user_id).order_by(
        WorkSession.started_at.desc()
    )
    total = query.count()
    return query.offset(offset).limit(limit).all(), total


def update_session(
    db: Session, session_id: str, user_id: str, data: WorkSessionUpdate
) -> WorkSession:
    session = (
        db.query(WorkSession)
        .filter(WorkSession.id == session_id, WorkSession.user_id == user_id)
        .first()
    )
    if not session:
        raise NotFoundError("Sesión de trabajo no encontrada")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(session, field, value)
    db.commit()
    db.refresh(session)
    return session


def get_session_duration_seconds(session: WorkSession) -> int:
    """Return total session duration in seconds."""
    if session.ended_at and session.started_at:
        return int((session.ended_at - session.started_at).total_seconds())
    return session.total_active_seconds
