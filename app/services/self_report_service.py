"""Self-report service: create and list self-reports."""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.exceptions import ForbiddenError, NotFoundError
from app.models.self_report import SelfReport
from app.models.session import WorkSession
from app.schemas.self_report import SelfReportCreate
from app.services import consent_service


def create_report(db: Session, user_id: str, data: SelfReportCreate) -> SelfReport:
    consent = consent_service.get_latest_consent(db, user_id)
    if consent is None or not consent.granted:
        raise ForbiddenError(
            "Se requiere consentimiento de recolección de datos antes de guardar autorreportes"
        )
    if data.session_id:
        owned = (
            db.query(WorkSession.id)
            .filter(
                WorkSession.id == data.session_id,
                WorkSession.user_id == user_id,
            )
            .first()
        )
        if not owned:
            raise NotFoundError("Sesión de trabajo no encontrada")

    report = SelfReport(
        user_id=user_id,
        session_id=data.session_id,
        reported_at=datetime.now(timezone.utc),
        fatigue_level=data.fatigue_level,
        stress_level=data.stress_level,
        concentration_level=data.concentration_level,
        task_difficulty=data.task_difficulty,
        perceived_effort=data.perceived_effort,
        need_for_break=data.need_for_break,
        sleep_hours=data.sleep_hours,
        sleep_quality=data.sleep_quality,
        rest_quality_previous_night=data.rest_quality_previous_night,
        notes=data.notes,
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return report


def list_reports(
    db: Session, user_id: str, offset: int = 0, limit: int = 20
) -> tuple[list[SelfReport], int]:
    query = db.query(SelfReport).filter(SelfReport.user_id == user_id).order_by(
        SelfReport.reported_at.desc()
    )
    total = query.count()
    return query.offset(offset).limit(limit).all(), total
