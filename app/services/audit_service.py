"""Audit log service — append-only security event logging."""

from sqlalchemy.orm import Session

from app.models.compliance import AuditLog


def log_event(
    db: Session,
    action: str,
    actor_id: str | None = None,
    actor_email: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    ip_address: str | None = None,
    detail: str | None = None,
) -> AuditLog:
    """Write an immutable audit entry."""
    entry = AuditLog(
        actor_id=actor_id,
        actor_email=actor_email,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        ip_address=ip_address,
        detail=detail,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry
