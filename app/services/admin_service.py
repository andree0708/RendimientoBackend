"""Administration service — aggregated, anonymized statistics."""

from sqlalchemy.orm import Session

from app.models.compliance import AuditLog
from app.models.session import WorkSession
from app.models.user import User


def get_aggregate_stats(db: Session) -> dict:
    """Return aggregate organization-level stats.

    Individual data is intentionally excluded; only totals and averages
    are exposed so this cannot be used for individual surveillance.
    """
    total_users = db.query(User).filter(User.is_active.is_(True)).count()
    total_sessions = db.query(WorkSession).count()
    active_sessions = db.query(WorkSession).filter(WorkSession.status == "active").count()
    return {
        "total_active_users": total_users,
        "total_sessions": total_sessions,
        "active_sessions_now": active_sessions,
    }


def get_audit_logs(db: Session, skip: int = 0, limit: int = 50) -> list:
    logs = db.query(AuditLog).order_by(AuditLog.created_at.desc()).offset(skip).limit(limit).all()
    return [
        {
            "id": l.id,
            "action": l.action,
            "actor_email": l.actor_email,
            "resource_type": l.resource_type,
            "resource_id": l.resource_id,
            "detail": l.detail,
            "created_at": l.created_at.isoformat() if l.created_at else None,
        }
        for l in logs
    ]
