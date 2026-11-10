"""Recommendation service — generate, list, and update recommendations."""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.models.recommendation import Recommendation
from app.schemas.recommendation import RecommendationUpdate
from app.websocket.manager import ws_manager


def create_recommendation(
    db: Session,
    user_id: str,
    category: str,
    title: str,
    body: str,
    reason: str | None = None,
    session_id: str | None = None,
    priority: str = "normal",
) -> Recommendation:
    """Persist a new recommendation."""
    rec = Recommendation(
        user_id=user_id,
        session_id=session_id,
        generated_at=datetime.now(timezone.utc),
        category=category,
        title=title,
        body=body,
        reason=reason,
        status="pending",
        priority=priority,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec


async def create_and_push(
    db: Session,
    user_id: str,
    category: str,
    title: str,
    body: str,
    reason: str | None = None,
    session_id: str | None = None,
    priority: str = "normal",
) -> Recommendation:
    """Persist a recommendation and notify the user over WebSocket."""
    rec = create_recommendation(db, user_id, category, title, body, reason, session_id, priority)
    await ws_manager.send_to_user(
        user_id=user_id,
        event_type="recommendation.created",
        payload={
            "recommendation_id": rec.id,
            "category": category,
            "title": title,
            "body": body,
            "priority": priority,
        },
        session_id=session_id,
    )
    return rec


def list_recommendations(
    db: Session, user_id: str, status_filter: str | None = None, offset: int = 0, limit: int = 20
) -> tuple[list[Recommendation], int]:
    query = (
        db.query(Recommendation)
        .filter(Recommendation.user_id == user_id)
        .order_by(Recommendation.generated_at.desc())
    )
    if status_filter:
        query = query.filter(Recommendation.status == status_filter)
    total = query.count()
    return query.offset(offset).limit(limit).all(), total


def update_recommendation(
    db: Session, rec_id: str, user_id: str, data: RecommendationUpdate
) -> Recommendation:
    rec = (
        db.query(Recommendation)
        .filter(Recommendation.id == rec_id, Recommendation.user_id == user_id)
        .first()
    )
    if not rec:
        raise NotFoundError("Recommendation not found")
    if data.status:
        rec.status = data.status
    db.commit()
    db.refresh(rec)
    return rec
