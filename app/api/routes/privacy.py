"""Privacy routes — user data export and deletion."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.services import audit_service, privacy_service

router = APIRouter(prefix="/privacy", tags=["privacy"])


def _client_ip(request: Request) -> str | None:
    if request.client is None:
        return None
    return request.client.host


@router.get("/export")
def export_my_data(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Download every record stored for the authenticated user as JSON."""
    data = privacy_service.export_user_data(db, current_user)
    audit_service.log_event(
        db,
        action="privacy.export",
        actor_id=current_user.id,
        actor_email=current_user.email,
        resource_type="user_data",
        resource_id=current_user.id,
        ip_address=_client_ip(request),
        detail=(
            f"sessions={len(data['sessions'])}; "
            f"metrics={len(data['activity_metrics'])}; "
            f"self_reports={len(data['self_reports'])}"
        ),
    )
    return data


@router.delete("/data")
def delete_my_data(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete all collected data for the authenticated user.

    The account itself is kept; the latest consent record is retained and
    marked as withdrawn as an audit trail.
    """
    result = privacy_service.delete_user_data(db, current_user)
    audit_service.log_event(
        db,
        action="privacy.delete",
        actor_id=current_user.id,
        actor_email=current_user.email,
        resource_type="user_data",
        resource_id=current_user.id,
        ip_address=_client_ip(request),
        detail=(
            f"sessions={result['deleted']['sessions']}; "
            f"metrics={result['deleted']['activity_metrics']}; "
            f"self_reports={result['deleted']['self_reports']}; "
            f"consent_withdrawn={result['deleted']['consent_withdrawn']}"
        ),
    )
    return result
