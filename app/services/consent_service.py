"""Consent service — manage informed consent records."""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ValidationError
from app.models.compliance import ConsentRecord

VALID_SCOPES = frozenset({"all", "activity_only", "app_usage_only", "minimal"})

SCOPE_DESCRIPTIONS = {
    "all": "Full collection: timing, pauses, app usage and work output.",
    "activity_only": "Timing only: app-tracking fields are never stored.",
    "app_usage_only": "Activity timing plus app usage, without work-output counts.",
    "minimal": "Minimal timing only: only interval/active/idle/continuous work.",
}


def get_latest_consent(db: Session, user_id: str) -> ConsentRecord | None:
    """Return the most recent consent record, or None if the user has none.

    ``created_at`` uses a second-precision server default on SQLite, so two
    records created within the same second would tie. Python-side
    ``granted_at``/``withdrawn_at`` carry microsecond precision and break
    the tie deterministically.
    """
    return (
        db.query(ConsentRecord)
        .filter(ConsentRecord.user_id == user_id)
        .order_by(
            ConsentRecord.created_at.desc(),
            ConsentRecord.granted_at.desc(),
            ConsentRecord.withdrawn_at.desc(),
        )
        .first()
    )


def get_consent(db: Session, user_id: str) -> ConsentRecord:
    record = get_latest_consent(db, user_id)
    if not record:
        raise NotFoundError("No hay registro de consentimiento")
    return record


def list_consent_history(db: Session, user_id: str) -> list[ConsentRecord]:
    """Full consent history for transparency (newest first)."""
    return (
        db.query(ConsentRecord)
        .filter(ConsentRecord.user_id == user_id)
        .order_by(
            ConsentRecord.created_at.desc(),
            ConsentRecord.granted_at.desc(),
            ConsentRecord.withdrawn_at.desc(),
        )
        .all()
    )


def grant_consent(db: Session, user_id: str, scope: str = "all") -> ConsentRecord:
    """Record that the user has granted informed consent."""
    now = datetime.now(timezone.utc)
    record = ConsentRecord(
        user_id=user_id,
        granted=True,
        scope=scope,
        version="1.0",
        granted_at=now,
        created_at=now,
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


def set_consent(
    db: Session, user_id: str, granted: bool, scope: str = "all"
) -> ConsentRecord:
    """Grant or withdraw consent, creating a record when none exists."""
    if scope not in VALID_SCOPES:
        raise ValidationError(
            f"Alcance de consentimiento inválido '{scope}'. "
            f"Permitidos: {sorted(VALID_SCOPES)}"
        )
    if granted:
        return grant_consent(db, user_id, scope)

    record = get_latest_consent(db, user_id)
    if record is None:
        now = datetime.now(timezone.utc)
        record = ConsentRecord(
            user_id=user_id,
            granted=False,
            scope=scope,
            version="1.0",
            withdrawn_at=now,
            created_at=now,
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        return record

    if record.granted:
        return withdraw_consent(db, user_id)
    return record
