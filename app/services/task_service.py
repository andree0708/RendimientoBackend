"""Task management service."""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.models.task import Task, TaskResult
from app.schemas.task import TaskCreate, TaskResultCreate, TaskUpdate


def create_task(db: Session, user_id: str, data: TaskCreate) -> Task:
    task = Task(
        user_id=user_id,
        session_id=data.session_id,
        title=data.title,
        description=data.description,
        estimated_seconds=data.estimated_seconds,
        complexity=data.complexity,
        status="pending",
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def get_task(db: Session, task_id: str, user_id: str) -> Task:
    task = db.query(Task).filter(Task.id == task_id, Task.user_id == user_id).first()
    if not task:
        raise NotFoundError("Task not found")
    return task


def list_tasks(
    db: Session, user_id: str, status_filter: str | None = None, offset: int = 0, limit: int = 20
) -> tuple[list[Task], int]:
    query = db.query(Task).filter(Task.user_id == user_id).order_by(Task.created_at.desc())
    if status_filter:
        query = query.filter(Task.status == status_filter)
    total = query.count()
    return query.offset(offset).limit(limit).all(), total


def update_task(db: Session, task_id: str, user_id: str, data: TaskUpdate) -> Task:
    task = get_task(db, task_id, user_id)
    updates = data.model_dump(exclude_unset=True)

    # If status changes to completed, set completed_at and compute actual seconds
    if updates.get("status") == "completed" and task.status != "completed":
        if task.started_at:
            now = data.completed_at or datetime.now(timezone.utc)
            task.actual_seconds = int((now - task.started_at).total_seconds())
        task.completed_at = data.completed_at or datetime.now(timezone.utc)

    if updates.get("status") == "in_progress" and not task.started_at:
        task.started_at = datetime.now(timezone.utc)

    for field, value in updates.items():
        if field not in ("completed_at",):
            setattr(task, field, value)

    db.commit()
    db.refresh(task)
    return task


def add_result(
    db: Session, task_id: str, user_id: str, data: TaskResultCreate
) -> TaskResult:
    task = get_task(db, task_id, user_id)
    deviation = task.actual_seconds - task.estimated_seconds
    result = TaskResult(
        task_id=task.id,
        outcome=data.outcome,
        errors_count=data.errors_count,
        quality_rating=data.quality_rating,
        notes=data.notes,
        deviation_seconds=deviation,
    )
    db.add(result)
    db.commit()
    db.refresh(result)
    return result
