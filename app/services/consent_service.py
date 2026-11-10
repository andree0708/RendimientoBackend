"""Consent service — manage informed consent records."""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.models.compliance import ConsentRecord


def get_consent(db: Session, user_id: str) -> ConsentRecord:
    record = (
        db.query(ConsentRecord)
        .filter(ConsentRecord.user_id == user_id)
        .order_by(ConsentRecord.created_at.desc())
        .first()
    )
    if not record:
        raise NotFoundError("No consent record found")
    return record


def grant_consent(db: Session, user_id: str, scope: str = "all") -> ConsentRecord:
    """Record that the user has granted informed consent."""
    record = ConsentRecord(
        user_id=user_id,
        granted=True,
        scope=scope,
        version="1.0",
        granted_at=datetime.now(timezone.utc),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def withdraw_consent(db: Session, user_id: str) -> ConsentRecord:
    """Record that the user has withdrawn consent."""
    record = get_consent(db, user_id)
    record.granted = False
    record.withdrawn_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(record)
    return record
