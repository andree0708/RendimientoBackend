"""Self-report routes."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_pagination
from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.pagination import paginate
from app.models.user import User
from app.schemas.self_report import SelfReportCreate, SelfReportPage, SelfReportRead
from app.services import self_report_service
from app.websocket.manager import ws_manager

router = APIRouter(prefix="/self-reports", tags=["self-reports"])


@router.post("", response_model=SelfReportRead, status_code=201)
async def create_report(
    data: SelfReportCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    report = self_report_service.create_report(db, current_user.id, data)
    await ws_manager.send_to_user(
        current_user.id,
        "self_report.submitted",
        {
            "report_id": report.id,
            "fatigue_level": report.fatigue_level,
            "stress_level": report.stress_level,
        },
        session_id=data.session_id,
    )
    return report


@router.get("", response_model=SelfReportPage)
def list_reports(
    pagination=Depends(get_pagination),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    reports, total = self_report_service.list_reports(db, current_user.id, pagination.offset, pagination.limit)
    return paginate([SelfReportRead.model_validate(r) for r in reports], total, pagination)
