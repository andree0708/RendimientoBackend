"""Seeded demo rows must never reach ML training data."""

from datetime import datetime, timezone

from app.ai import pipeline
from app.models.self_report import SelfReport
from app.models.session import ActivityMetric, WorkSession


def test_load_real_data_excludes_demo_rows(db, test_user):
    user, _ = test_user
    now = datetime.now(timezone.utc)

    real_session = WorkSession(
        user_id=user.id, started_at=now, status="completed", is_demo=False
    )
    demo_session = WorkSession(
        user_id=user.id, started_at=now, status="completed", is_demo=True
    )
    db.add_all([real_session, demo_session])
    db.flush()

    def metric(session_id, is_demo):
        return ActivityMetric(
            session_id=session_id,
            user_id=user.id,
            recorded_at=now,
            interval_seconds=60,
            active_seconds=50,
            idle_seconds=10,
            is_demo=is_demo,
        )

    # 60 real metrics (above the 50-sample minimum) + 60 demo metrics on the
    # demo session + 5 demo metrics wrongly attached to the real session.
    db.add_all([metric(real_session.id, False) for _ in range(60)])
    db.add_all([metric(demo_session.id, True) for _ in range(60)])
    db.add_all([metric(real_session.id, True) for _ in range(5)])

    def report(session_id, is_demo):
        return SelfReport(
            user_id=user.id,
            session_id=session_id,
            reported_at=now,
            fatigue_level=3,
            stress_level=2,
            concentration_level=4,
            task_difficulty=3,
            perceived_effort=3,
            need_for_break=2,
            is_demo=is_demo,
        )

    db.add(report(real_session.id, False))
    db.add(report(demo_session.id, True))
    db.add(report(None, True))
    db.commit()

    metrics_df, reports_df = pipeline._load_real_data(db, user.id)

    assert len(metrics_df) == 60
    assert len(reports_df) == 1
    assert reports_df.iloc[0]["session_id"] == real_session.id
