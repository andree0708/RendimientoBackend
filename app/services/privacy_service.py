"""Privacy service — export and deletion of a user's collected data."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.inspection import inspect as sa_inspect
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.ai import FatigueAssessment, PerformancePrediction
from app.models.compliance import AgentDevice, ConsentRecord
from app.models.notification import Notification
from app.models.recommendation import Recommendation
from app.models.self_report import SelfReport
from app.models.session import ActivityMetric, WorkSession
from app.models.task import Task, TaskResult
from app.models.user import User


def _serialize(obj) -> dict:
    """Convert an ORM row to a plain dict without relationships."""
    return {
        attr.key: getattr(obj, attr.key)
        for attr in sa_inspect(obj).mapper.column_attrs
    }


def _serialize_all(rows) -> list[dict]:
    return [_serialize(row) for row in rows]


def export_user_data(db: Session, user: User) -> dict:
    """Return every record stored for a user in a machine-readable format."""
    task_ids = select(Task.id).where(Task.user_id == user.id)

    return {
        "exported_at": datetime.now(timezone.utc),
        "user": {
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "avatar_url": user.avatar_url,
            "preferred_scale_max": user.preferred_scale_max,
            "organization_id": user.organization_id,
            "created_at": user.created_at,
        },
        "consent_records": _serialize_all(
            db.query(ConsentRecord)
            .filter(ConsentRecord.user_id == user.id)
            .order_by(ConsentRecord.created_at)
            .all()
        ),
        "sessions": _serialize_all(
            db.query(WorkSession)
            .filter(WorkSession.user_id == user.id)
            .order_by(WorkSession.started_at)
            .all()
        ),
        "activity_metrics": _serialize_all(
            db.query(ActivityMetric)
            .filter(ActivityMetric.user_id == user.id)
            .order_by(ActivityMetric.recorded_at)
            .all()
        ),
        "self_reports": _serialize_all(
            db.query(SelfReport)
            .filter(SelfReport.user_id == user.id)
            .order_by(SelfReport.reported_at)
            .all()
        ),
        "tasks": _serialize_all(
            db.query(Task)
            .filter(Task.user_id == user.id)
            .order_by(Task.created_at)
            .all()
        ),
        "task_results": _serialize_all(
            db.query(TaskResult)
            .filter(TaskResult.task_id.in_(task_ids))
            .order_by(TaskResult.created_at)
            .all()
        ),
        "fatigue_assessments": _serialize_all(
            db.query(FatigueAssessment)
            .filter(FatigueAssessment.user_id == user.id)
            .order_by(FatigueAssessment.assessed_at)
            .all()
        ),
        "performance_predictions": _serialize_all(
            db.query(PerformancePrediction)
            .filter(PerformancePrediction.user_id == user.id)
            .order_by(PerformancePrediction.predicted_at)
            .all()
        ),
        "recommendations": _serialize_all(
            db.query(Recommendation)
            .filter(Recommendation.user_id == user.id)
            .order_by(Recommendation.generated_at)
            .all()
        ),
        "notifications": _serialize_all(
            db.query(Notification)
            .filter(Notification.user_id == user.id)
            .order_by(Notification.created_at)
            .all()
        ),
        "agent_devices": _serialize_all(
            db.query(AgentDevice)
            .filter(AgentDevice.user_id == user.id)
            .order_by(AgentDevice.created_at)
            .all()
        ),
    }


def delete_user_data(db: Session, user: User) -> dict:
    """Delete all collected data for a user while keeping the account.

    The latest consent record is kept (marked as withdrawn) as an audit
    trail of the privacy decision; every collected data point is removed.
    """
    session_ids = select(WorkSession.id).where(WorkSession.user_id == user.id)
    task_ids = select(Task.id).where(Task.user_id == user.id)

    counts: dict[str, int | bool] = {}

    counts["task_results"] = (
        db.query(TaskResult)
        .filter(TaskResult.task_id.in_(task_ids))
        .delete(synchronize_session=False)
    )
    counts["tasks"] = (
        db.query(Task)
        .filter(Task.user_id == user.id)
        .delete(synchronize_session=False)
    )
    counts["activity_metrics"] = (
        db.query(ActivityMetric)
        .filter(ActivityMetric.user_id == user.id)
        .delete(synchronize_session=False)
    )
    counts["self_reports"] = (
        db.query(SelfReport)
        .filter(SelfReport.user_id == user.id)
        .delete(synchronize_session=False)
    )
    counts["fatigue_assessments"] = (
        db.query(FatigueAssessment)
        .filter(FatigueAssessment.user_id == user.id)
        .delete(synchronize_session=False)
    )
    counts["performance_predictions"] = (
        db.query(PerformancePrediction)
        .filter(PerformancePrediction.user_id == user.id)
        .delete(synchronize_session=False)
    )
    counts["recommendations"] = (
        db.query(Recommendation)
        .filter(Recommendation.user_id == user.id)
        .delete(synchronize_session=False)
    )
    counts["notifications"] = (
        db.query(Notification)
        .filter(Notification.user_id == user.id)
        .delete(synchronize_session=False)
    )
    counts["agent_devices"] = (
        db.query(AgentDevice)
        .filter(AgentDevice.user_id == user.id)
        .delete(synchronize_session=False)
    )
    counts["sessions"] = (
        db.query(WorkSession)
        .filter(WorkSession.user_id == user.id)
        .delete(synchronize_session=False)
    )

    consent = (
        db.query(ConsentRecord)
        .filter(ConsentRecord.user_id == user.id)
        .order_by(ConsentRecord.created_at.desc())
        .first()
    )
    counts["consent_withdrawn"] = bool(consent and consent.granted)
    if consent and consent.granted:
        consent.granted = False
        consent.withdrawn_at = datetime.now(timezone.utc)

    db.commit()
    return {
        "deleted": counts,
        "account_retained": True,
        "consent_record_retained": consent is not None,
    }


def purge_old_metrics(db: Session, retention_days: int | None = None) -> int:
    """Delete activity metrics older than the retention window.

    Returns the number of rows deleted. Admin-only caller responsibility.
    """
    days = retention_days if retention_days is not None else settings.PRIVACY_RETENTION_DAYS
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    deleted = (
        db.query(ActivityMetric)
        .filter(ActivityMetric.recorded_at < cutoff)
        .delete(synchronize_session=False)
    )
    db.commit()
    return deleted
