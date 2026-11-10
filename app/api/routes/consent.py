"""Consent routes — read and update the user's informed-consent status."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.consent import ConsentRead, ConsentUpdate
from app.services import audit_service, consent_service

router = APIRouter(prefix="/consent", tags=["consent"])


@router.get("", response_model=ConsentRead)
def get_consent(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    record = consent_service.get_latest_consent(db, current_user.id)
    if record is None:
        return ConsentRead(granted=False, scope="all", version="1.0")
    return record


@router.get("/history", response_model=list[ConsentRead])
def get_consent_history(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Full consent history for transparency (newest first)."""
    return consent_service.list_consent_history(db, current_user.id)


@router.post("", response_model=ConsentRead)
def update_consent(
    data: ConsentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    record = consent_service.set_consent(
        db, current_user.id, data.granted, data.scope
    )
    audit_service.log_event(
        db,
        action="consent.updated",
        actor_id=current_user.id,
        actor_email=current_user.email,
        resource_type="consent_record",
        resource_id=record.id,
        detail=f"granted={record.granted}; scope={record.scope}",
    )
    return record
