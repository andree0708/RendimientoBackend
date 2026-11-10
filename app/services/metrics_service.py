"""Activity metrics service: ingest agent batches, update session aggregates."""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.exceptions import ForbiddenError, NotFoundError, ValidationError
from app.models.session import ActivityMetric, WorkSession
from app.schemas.metrics import ActivityMetricBatch, ActivityMetricItem
from app.services import consent_service

MAX_METRICS_PER_BATCH = 500
MAX_FUTURE_SKEW_SECONDS = 300  # recorded_at more than 5 min in the future is rejected


def _apply_scope(item: ActivityMetricItem, scope: str) -> ActivityMetricItem:
    """Redact fields outside the user's consented scope.

    - all: store everything as received.
    - activity_only: timing only; app-tracking fields are zeroed.
    - app_usage_only: timing plus app usage; work-output counts are zeroed.
    - minimal: only interval/active/idle/continuous work are kept.
    """
    if scope == "all":
        return item
    if scope == "activity_only":
        item.app_switch_count = 0
        item.interruptions_count = 0
        item.app_category_id = None
        item.app_category_seconds = 0
        return item
    if scope == "app_usage_only":
        item.tasks_started = 0
        item.tasks_completed = 0
        item.errors_reported = 0
        return item
    if scope == "minimal":
        item.pause_count = 0
        item.pause_total_seconds = 0
        item.app_switch_count = 0
        item.interruptions_count = 0
        item.app_category_id = None
        item.app_category_seconds = 0
        item.tasks_started = 0
        item.tasks_completed = 0
        item.errors_reported = 0
        return item
    return item


def ingest_batch(db: Session, user_id: str, batch: ActivityMetricBatch) -> list[ActivityMetric]:
    """Store a batch of metrics and update the parent session aggregates.

    Collection requires an active consent record. Withdrawing consent stops
    ingestion immediately instead of silently continuing to store data.
    """
    consent = consent_service.get_latest_consent(db, user_id)
    if consent is None or not consent.granted:
        raise ForbiddenError(
            "Se requiere consentimiento de recolección de datos antes de poder enviar métricas"
        )
    scope = consent.scope or "all"
    if scope not in consent_service.VALID_SCOPES:
        scope = "all"

    session = (
        db.query(WorkSession)
        .filter(WorkSession.id == batch.session_id, WorkSession.user_id == user_id)
        .first()
    )
    if not session:
        raise NotFoundError("Sesión de trabajo no encontrada")

    if len(batch.metrics) > MAX_METRICS_PER_BATCH:
        raise ValidationError(
            f"Lote demasiado grande: {len(batch.metrics)} elementos "
            f"(máximo {MAX_METRICS_PER_BATCH})"
        )

    now = datetime.now(timezone.utc)
    for item in batch.metrics:
        recorded = item.recorded_at
        if recorded.tzinfo is None:
            recorded = recorded.replace(tzinfo=timezone.utc)
        if (recorded - now).total_seconds() > MAX_FUTURE_SKEW_SECONDS:
            raise ValidationError(
                "recorded_at no puede estar en el futuro"
            )
        if item.active_seconds + item.idle_seconds > item.interval_seconds + 5:
            raise ValidationError(
                "active_seconds + idle_seconds supera a interval_seconds"
            )

    created: list[ActivityMetric] = []
    for item in batch.metrics:
        item = _apply_scope(item, scope)
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

        # Every metric row represents one interval; the agent sends deltas for
        # pause/task/error counters, so they accumulate normally.
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
    user_id: str,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[ActivityMetric], int]:
    query = (
        db.query(ActivityMetric)
        .filter(
            ActivityMetric.session_id == session_id,
            ActivityMetric.user_id == user_id,
        )
        .order_by(ActivityMetric.recorded_at.desc())
    )
    total = query.count()
    return query.offset(offset).limit(limit).all(), total
