"""Seed realistic DEMO data for showcasing the UI.

Every generated row is marked ``is_demo=True`` and is therefore EXCLUDED
from ML training (see ``pipeline._load_real_data``). Seeded sessions carry
a clear note. Model outputs (fatigue assessments, performance predictions,
recommendations) are NEVER fabricated.

Usage (from RendimientoBackend):
    $env:DATABASE_URL='sqlite:///./worksense.db'
    .\\.venv\\Scripts\\python.exe scripts/seed_demo.py --email demo@worksense.ai
    .\\.venv\\Scripts\\python.exe scripts/seed_demo.py --email demo@worksense.ai --clear
"""

import argparse
import random
from datetime import datetime, timedelta, timezone

from app.core.database import SessionLocal
from app.models.session import ActivityMetric, WorkSession
from app.models.self_report import SelfReport
from app.models.task import Task, TaskResult
from app.models.user import User

SEED = 42
SEED_NOTE = "Datos sintéticos de demostración (seed, is_demo=True)."

TASK_TITLES = [
    ("Revisar pull requests del sprint", "development", 3),
    ("Corregir bug de paginación en sesiones", "development", 4),
    ("Escribir pruebas del servicio de métricas", "development", 3),
    ("Documentar endpoints de privacidad", "productivity", 2),
    ("Responder correos pendientes", "communication", 1),
    ("Preparar demo para el equipo", "productivity", 3),
    ("Refactorizar pipeline de features", "development", 5),
    ("Actualizar dependencias del frontend", "development", 2),
    ("Revisar diseño del dashboard", "productivity", 2),
    ("Investigar pico de latencia en /metrics/batch", "development", 4),
    ("Planificar tareas de la semana", "productivity", 1),
    ("Leer RFC de rate limiting", "browser", 2),
    ("Optimizar consulta de audit logs", "development", 3),
    ("Probar flujo de consentimiento", "development", 2),
    ("Limpieza de ramas git antiguas", "terminal", 1),
    ("Revisar alertas de seguridad", "browser", 3),
    ("Migrar esquema de consentimiento", "development", 4),
    ("Escribir changelog del release", "productivity", 1),
]

CATEGORIES = ["development", "browser", "communication", "productivity", "terminal", "other"]
CATEGORY_WEIGHTS = [0.42, 0.24, 0.10, 0.15, 0.05, 0.04]


def _workdays(days_back: int, ref: datetime) -> list:
    days = []
    d = ref.date() - timedelta(days=days_back)
    while len(days) < 10:
        if d.weekday() < 5:  # Mon-Fri
            days.append(d)
        d += timedelta(days=1)
    # One light Saturday session for realism.
    sat = ref.date() - timedelta(days=(ref.date().weekday() + 2) % 7 or 7)
    days.append(sat)
    return sorted(days)


def seed(email: str, days_back: int = 14, clear: bool = False) -> dict:
    rng = random.Random(SEED)
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if not user:
            raise SystemExit(f"User not found: {email}")

        if clear:
            demo_session_ids = [
                s.id for s in db.query(WorkSession.id)
                .filter(WorkSession.user_id == user.id, WorkSession.is_demo.is_(True))
                .all()
            ]
            if demo_session_ids:
                db.query(ActivityMetric).filter(
                    ActivityMetric.session_id.in_(demo_session_ids)
                ).delete(synchronize_session=False)
                db.query(SelfReport).filter(
                    SelfReport.session_id.in_(demo_session_ids)
                ).delete(synchronize_session=False)
                db.query(WorkSession).filter(
                    WorkSession.id.in_(demo_session_ids)
                ).delete(synchronize_session=False)
            db.query(Task).filter(
                Task.user_id == user.id, Task.title.like("SEED:%")
            ).delete(synchronize_session=False)
            db.commit()

        now = datetime.now(timezone.utc)
        counts = {"sessions": 0, "metrics": 0, "reports": 0, "tasks": 0, "results": 0}

        sessions: list[WorkSession] = []
        for day in _workdays(days_back, now):
            start_hour = rng.choice([8, 9, 9, 10])
            start_min = rng.choice([0, 15, 30, 45])
            started = datetime(
                day.year, day.month, day.day, start_hour, start_min,
                tzinfo=timezone.utc,
            )
            if started > now - timedelta(hours=2):
                continue  # don't seed the immediate present
            is_saturday = day.weekday() == 5
            duration_h = rng.uniform(2.5, 4.0) if is_saturday else rng.uniform(6.5, 8.5)
            ended = started + timedelta(hours=duration_h)

            session = WorkSession(
                user_id=user.id,
                started_at=started,
                ended_at=ended,
                status="completed",
                notes=SEED_NOTE,
                is_demo=True,
            )
            db.add(session)
            db.flush()
            sessions.append(session)
            counts["sessions"] += 1

            # --- metrics: one row per 60 s interval ---
            # Counters are per-interval DELTAS (agent/backend convention).
            metrics: list[ActivityMetric] = []
            total_active = total_idle = total_pause = 0
            pause_count = 0
            continuous = 0
            t = started
            lunch_start = started.replace(hour=13, minute=0)
            lunch_end = started.replace(hour=14, minute=0)
            prev_started = prev_completed = prev_errors = 0
            paused_midday = False
            while t < ended:
                in_lunch = lunch_start <= t < lunch_end
                if in_lunch and not paused_midday and rng.random() < 0.08:
                    paused_midday = True
                    pause_count += 1
                    pause_delta, pause_total = 1, rng.randint(1500, 3300)
                    total_pause += pause_total
                else:
                    pause_delta, pause_total = 0, 0

                if in_lunch:
                    active = rng.randint(2, 12)
                else:
                    active = rng.randint(28, 58)
                idle = 60 - active
                continuous = 0 if idle > 20 else continuous + 60

                if rng.random() < 0.02:
                    new_started = prev_started + 1
                else:
                    new_started = prev_started
                if new_started > prev_completed and rng.random() < 0.6:
                    new_completed = prev_completed + 1
                else:
                    new_completed = prev_completed
                new_errors = prev_errors + (1 if rng.random() < 0.008 else 0)

                category = rng.choices(CATEGORIES, weights=CATEGORY_WEIGHTS)[0]
                metrics.append(ActivityMetric(
                    session_id=session.id,
                    user_id=user.id,
                    recorded_at=t,
                    interval_seconds=60,
                    active_seconds=active,
                    idle_seconds=idle,
                    continuous_work_seconds=continuous,
                    pause_count=pause_delta,
                    pause_total_seconds=pause_total,
                    app_switch_count=rng.randint(0, 5) if not in_lunch else rng.randint(0, 2),
                    interruptions_count=0,
                    app_category_id=None,
                    app_category_seconds=active if category != "other" else 0,
                    tasks_started=new_started - prev_started,
                    tasks_completed=new_completed - prev_completed,
                    errors_reported=new_errors - prev_errors,
                    is_demo=True,
                ))
                prev_started, prev_completed, prev_errors = new_started, new_completed, new_errors
                total_active += active
                total_idle += idle
                t += timedelta(seconds=60)

            session.total_active_seconds = total_active
            session.total_idle_seconds = total_idle
            session.total_pause_seconds = total_pause
            session.pause_count = pause_count
            db.add_all(metrics)
            counts["metrics"] += len(metrics)

            # --- self-report: mid-afternoon check-in ---
            report_at = started.replace(hour=15, minute=30)
            if report_at < ended and report_at < now - timedelta(hours=1):
                fatigue = max(1, min(5, 2 + int((ended - started).seconds / 3600) - 4 + rng.randint(0, 2)))
                db.add(SelfReport(
                    user_id=user.id,
                    session_id=session.id,
                    reported_at=report_at,
                    fatigue_level=fatigue,
                    stress_level=rng.randint(1, 4),
                    concentration_level=rng.randint(2, 5),
                    task_difficulty=rng.randint(1, 5),
                    perceived_effort=rng.randint(1, 5),
                    need_for_break=max(1, min(5, fatigue + rng.randint(-1, 1))),
                    sleep_hours=round(rng.uniform(5.5, 8.0), 1),
                    sleep_quality=rng.randint(2, 5),
                    rest_quality_previous_night=rng.randint(2, 5),
                    notes="Seed demo" if rng.random() < 0.2 else None,
                    is_demo=True,
                ))
                counts["reports"] += 1

        db.commit()

        # --- tasks: prefixed SEED: so --clear can remove them ---
        statuses = (["completed"] * 12) + (["pending"] * 4) + (["in_progress"] * 2)
        rng.shuffle(statuses)
        base_day = now - timedelta(days=days_back)
        for i, (title, _cat, complexity) in enumerate(TASK_TITLES):
            status = statuses[i]
            created = base_day + timedelta(days=rng.randint(0, days_back - 1), hours=rng.randint(8, 17))
            estimated = rng.choice([900, 1800, 3600, 7200])
            task = Task(
                user_id=user.id,
                session_id=rng.choice(sessions).id if sessions and rng.random() < 0.6 else None,
                title=f"SEED: {title}",
                description=None,
                estimated_seconds=estimated,
                complexity=complexity,
                status=status,
            )
            if status in ("in_progress", "completed"):
                task.started_at = created + timedelta(hours=1)
            if status == "completed":
                actual = max(300, int(estimated * rng.uniform(0.6, 1.6)))
                task.actual_seconds = actual
                task.completed_at = task.started_at + timedelta(seconds=actual)
                db.add(task)
                db.flush()
                if rng.random() < 0.7:
                    db.add(TaskResult(
                        task_id=task.id,
                        outcome="completed",
                        errors_count=rng.randint(0, 2),
                        quality_rating=rng.randint(3, 5),
                        deviation_seconds=actual - estimated,
                    ))
                    counts["results"] += 1
            else:
                db.add(task)
            counts["tasks"] += 1

        db.commit()
        return counts
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed realistic DEMO data (is_demo=True).")
    parser.add_argument("--email", default="demo@worksense.ai")
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--clear", action="store_true",
                        help="Remove previously seeded demo rows first.")
    args = parser.parse_args()
    counts = seed(args.email, days_back=args.days, clear=args.clear)
    print(f"Seeded for {args.email}: {counts}")


if __name__ == "__main__":
    main()
