"""Task routes."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_pagination
from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.pagination import paginate
from app.models.user import User
from app.schemas.task import TaskCreate, TaskPage, TaskRead, TaskResultCreate, TaskResultRead, TaskUpdate
from app.services import task_service
from app.websocket.manager import ws_manager

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("", response_model=TaskRead, status_code=201)
async def create_task(
    data: TaskCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    task = task_service.create_task(db, current_user.id, data)
    await ws_manager.send_to_user(
        current_user.id,
        "task.created",
        {"task_id": task.id, "title": task.title, "complexity": task.complexity},
        session_id=data.session_id,
    )
    return task


@router.get("", response_model=TaskPage)
def list_tasks(
    status: str | None = Query(default=None),
    pagination=Depends(get_pagination),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tasks, total = task_service.list_tasks(db, current_user.id, status, pagination.offset, pagination.limit)
    return paginate([TaskRead.model_validate(t) for t in tasks], total, pagination)


@router.get("/{task_id}", response_model=TaskRead)
def get_task(
    task_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return task_service.get_task(db, task_id, current_user.id)


@router.patch("/{task_id}", response_model=TaskRead)
async def update_task(
    task_id: str,
    data: TaskUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    task = task_service.update_task(db, task_id, current_user.id, data)
    if task.status == "completed":
        await ws_manager.send_to_user(
            current_user.id,
            "task.completed",
            {"task_id": task.id, "actual_seconds": task.actual_seconds},
            session_id=task.session_id,
        )
    return task


@router.post("/{task_id}/results", response_model=TaskResultRead, status_code=201)
def add_task_result(
    task_id: str,
    data: TaskResultCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return task_service.add_result(db, task_id, current_user.id, data)
