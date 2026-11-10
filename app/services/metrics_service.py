"""Activity metrics service: ingest agent batches, update session aggregates."""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.models.session import ActivityMetric, WorkSession
from app.schemas.metrics import ActivityMetricBatch


def ingest_batch(db: Session, user_id: str, batch: ActivityMetricBatch) -> list[ActivityMetric]:
    """Store a batch of metrics and update the parent session aggregates."""
    session = (
        db.query(WorkSession)
        .filter(WorkSession.id == batch.session_id, WorkSession.user_id == user_id)
        .first()
    )
    if not session:
        raise NotFoundError("Work session not found")

    created: list[ActivityMetric] = []
    for item in batch.metrics:
        metric = ActivityMetric(
            session_id=session.id,
            user_id=user_id,
            recorded_at=item.recorded_at,
            interval_seconds=item.interval_seconds,
            active_seconds=item.active_seconds,
            idle_seconds=item.idle_seconds,
            continuous_work_seconds=item.continuous_work_seconds,
            pause_count=item.pause_count,
            pause_total_seconds=item.pause_total_seconds,
            app_switch_count=item.app_switch_count,
            interruptions_count=item.interruptions_count,
            app_category_id=item.app_category_id,
            app_category_seconds=item.app_category_seconds,
            tasks_started=item.tasks_started,
            tasks_completed=item.tasks_completed,
            errors_reported=item.errors_reported,
        )
        db.add(metric)
        created.append(metric)

        # Update session aggregates
        session.total_active_seconds += item.active_seconds
        session.total_idle_seconds += item.idle_seconds
        session.total_pause_seconds += item.pause_total_seconds
        session.pause_count += item.pause_count

    db.commit()
    for m in created:
        db.refresh(m)
    return created


def list_metrics(
    db: Session,
    session_id: str,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[ActivityMetric], int]:
    query = db.query(ActivityMetric).filter(ActivityMetric.session_id == session_id).order_by(
        ActivityMetric.recorded_at.desc()
    )
    total = query.count()
    return query.offset(offset).limit(limit).all(), total
