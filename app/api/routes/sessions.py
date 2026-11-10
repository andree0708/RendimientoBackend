"""Work session routes."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import get_pagination
from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.pagination import paginate
from app.models.user import User
from app.schemas.session import (
    WorkSessionCreate,
    WorkSessionPage,
    WorkSessionRead,
    WorkSessionUpdate,
)
from app.services import session_service
from app.websocket.manager import ws_manager

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("", response_model=WorkSessionRead, status_code=201)
async def start_session(
    data: WorkSessionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session = session_service.start_session(db, current_user, data.notes)
    await ws_manager.send_to_user(
        current_user.id,
        "session.started",
        {"session_id": session.id, "started_at": session.started_at.isoformat()},
        session_id=session.id,
    )
    return session


@router.post("/{session_id}/stop", response_model=WorkSessionRead)
async def stop_session(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session = session_service.stop_session(db, session_id, current_user.id)
    await ws_manager.send_to_user(
        current_user.id,
        "session.stopped",
        {"session_id": session.id, "ended_at": session.ended_at.isoformat() if session.ended_at else None},
        session_id=session.id,
    )
    return session


@router.get("", response_model=WorkSessionPage)
def list_sessions(
    pagination=Depends(get_pagination),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    sessions, total = session_service.list_sessions(db, current_user.id, pagination.offset, pagination.limit)
    return paginate([WorkSessionRead.model_validate(s) for s in sessions], total, pagination)


@router.get("/{session_id}", response_model=WorkSessionRead)
def get_session(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return session_service.get_session(db, session_id, current_user.id)


@router.patch("/{session_id}", response_model=WorkSessionRead)
def update_session(
    session_id: str,
    data: WorkSessionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return session_service.update_session(db, session_id, current_user.id, data)


@router.get("/active/current", response_model=WorkSessionRead | None)
def get_active_session(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return session_service.get_active_session(db, current_user.id)
