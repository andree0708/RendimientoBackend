"""LLM analysis layer (Groq, OpenAI-compatible API).

This layer READS the user's collected rows (real or seeded demo) and asks a
language model to produce a genuine, evidence-based analysis in Spanish:
fatigue assessment, performance forecast, anomalies and recommendations.

Honesty rules enforced here:
- Nothing is ever presented as a medical diagnosis (prompt + UI disclaimer).
- If the underlying rows are seeded demo data, the result is tagged
  ``data_basis="demo"`` end to end (DB JSON, API response, UI badge).
- The traditional ML pipeline (quality gates, never activating on synthetic
  data) is untouched; this is a separate, explicitly labeled path.
- Any API failure (no key, timeout, invalid JSON) returns ``None`` so the
  caller falls back to the honest "unavailable" state instead of inventing
  an answer.
"""

import json
import logging
from datetime import datetime, timedelta, timezone

import requests
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.self_report import SelfReport
from app.models.session import ActivityMetric, WorkSession
from app.models.task import Task

logger = logging.getLogger(__name__)

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

ALLOWED_RISKS = ("low", "moderate", "high")
ALLOWED_TRENDS = ("improving", "stable", "declining")
ALLOWED_SEVERITIES = ("low", "normal", "high")
ALLOWED_REC_CATEGORIES = ("break", "task_management", "schedule", "workload", "general")
ALLOWED_PRIORITIES = ("low", "normal", "high")


def is_configured() -> bool:
    """True when a Groq API key is configured."""
    return bool(settings.GROQ_API_KEY)


def build_evidence(db: Session, user_id: str, days: int = 14) -> tuple[str | None, str]:
    """Summarize the user's recent rows into a compact evidence text.

    Returns (evidence_text_or_None, data_basis) where data_basis is one of
    "real", "mixed", "demo" or "none".
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)

    sessions = (
        db.query(WorkSession)
        .filter(WorkSession.user_id == user_id, WorkSession.started_at >= since)
        .order_by(WorkSession.started_at.asc())
        .all()
    )
    if not sessions:
        return None, "none"

    demo_sessions = sum(1 for s in sessions if s.is_demo)
    if demo_sessions == 0:
        data_basis = "real"
    elif demo_sessions == len(sessions):
        data_basis = "demo"
    else:
        data_basis = "mixed"

    session_ids = [s.id for s in sessions]
    metrics = (
        db.query(ActivityMetric)
        .filter(
            ActivityMetric.user_id == user_id,
            ActivityMetric.session_id.in_(session_ids),
        )
        .all()
    )
    reports = (
        db.query(SelfReport)
        .filter(SelfReport.user_id == user_id, SelfReport.reported_at >= since)
        .order_by(SelfReport.reported_at.asc())
        .all()
    )
    tasks_done = (
        db.query(Task)
        .filter(Task.user_id == user_id, Task.status == "completed")
        .count()
    )
    tasks_open = (
        db.query(Task)
        .filter(Task.user_id == user_id, Task.status.in_(["pending", "in_progress"]))
        .count()
    )

    n_metrics = len(metrics)
    if metrics:
        total_active = sum(m.active_seconds for m in metrics)
        total_idle = sum(m.idle_seconds for m in metrics)
        total_pause = sum(m.pause_total_seconds for m in metrics)
        peak_continuous = max((m.continuous_work_seconds for m in metrics), default=0)
        total_errors = sum(m.errors_reported for m in metrics)
        total_switches = sum(m.app_switch_count for m in metrics)
        avg_active = total_active / n_metrics
        work_minutes = total_active / 60
    else:
        total_active = total_idle = total_pause = 0
        peak_continuous = total_errors = total_switches = 0
        avg_active = 0.0
        work_minutes = 0.0

    if reports:
        avg = lambda f: round(sum(getattr(r, f) for r in reports) / len(reports), 1)  # noqa: E731
        reports_line = (
            f"autorreportes={len(reports)}, fatiga_media={avg('fatigue_level')}/5, "
            f"estres_medio={avg('stress_level')}/5, concentracion_media={avg('concentration_level')}/5, "
            f"esfuerzo_medio={avg('perceived_effort')}/5, necesidad_pausa_media={avg('need_for_break')}/5, "
            f"horas_sueno_medias={avg('sleep_hours') if reports[0].sleep_hours is not None else 'n/d'}"
        )
    else:
        reports_line = "autorreportes=0 (el usuario no ha registrado cómo se siente)"

    lines = [
        f"sesiones_14d={len(sessions)} (demo={demo_sessions})",
        f"minutos_activos_totales={work_minutes:.0f}, media_seg_activos_por_intervalo={avg_active:.0f}",
        f"minutos_inactivos_totales={total_idle / 60:.0f}, pausas_totales_seg={total_pause}, racha_max_trabajo_continuo_min={peak_continuous / 60:.0f}",
        f"errores_reportados={total_errors}, cambios_de_app={total_switches}",
        reports_line,
        f"tareas_completadas={tasks_done}, tareas_abiertas={tasks_open}",
    ]
    return "\n".join(lines), data_basis


def _prompt(evidence: str) -> tuple[str, str]:
    system = (
        "Eres un analista de bienestar laboral. Analizas metadatos agregados de "
        "actividad (tiempos, pausas, autorreportes del 1 al 5) y devuelves SOLO "
        "un objeto JSON válido, sin texto fuera del JSON, sin bloques markdown. "
        "Todo el texto debe estar en español. PROHIBIDO dar diagnósticos médicos "
        "o mencionar enfermedades; habla solo de patrones de trabajo, descanso y "
        "carga. Si los datos son escasos, dilo con confianza baja."
    )
    user = (
        "Datos del trabajador (últimos 14 días):\n" + evidence + "\n\n"
        "Devuelve EXACTAMENTE este JSON (claves exactas, sin extras):\n"
        '{"fatigue": {"risk": "low|moderate|high", "probability": 0.0-1.0, '
        '"confidence": 0.0-1.0, "summary": "2 frases", '
        '"factors": [{"name": "texto corto", "weight": 0.0-1.0}]}, '
        '"performance": {"trend": "improving|stable|declining", '
        '"variation": número entre -1 y 1, "confidence": 0.0-1.0, '
        '"summary": "2 frases"}, '
        '"anomalies": [{"description": "1 frase", "severity": "low|normal|high"}], '
        '"recommendations": [{"category": "break|task_management|schedule|workload|general", '
        '"title": "título corto", "body": "1-2 frases accionables", '
        '"priority": "low|normal|high"}]}\n'
        "Máximo 5 factores, 5 anomalías y 3 recomendaciones."
    )
    return system, user


def _clamp(value, lo: float = 0.0, hi: float = 1.0, default: float = 0.5) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    if v != v:  # NaN
        return default
    return max(lo, min(hi, v))


def _clean_str(value, max_len: int = 500) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:max_len]


def _extract_candidates(text: str) -> list[str]:
    """Yield JSON candidate strings, most constrained first."""
    candidates = [text.strip()]
    # Fenced code blocks (```json ... ```), possibly several.
    parts = text.split("```")
    for part in parts[1:]:
        chunk = part.strip()
        if chunk.startswith("json"):
            chunk = chunk[4:].strip()
        if chunk.startswith("{") and chunk.endswith("}"):
            candidates.append(chunk)
    # Fallback: widest first-{ to last-} span.
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start:end + 1])
    # De-duplicate while preserving order.
    seen: set[str] = set()
    unique = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            unique.append(c)
    return unique


def _parse_response(content: object) -> dict | None:
    """Parse and validate model output; None when unusable."""
    if not isinstance(content, str):
        return None
    last_error = "empty"
    for candidate in _extract_candidates(content):
        try:
            payload = json.loads(candidate)
        except ValueError as exc:
            last_error = type(exc).__name__
            continue
        result = _validate(payload)
        if result is not None:
            return result
        last_error = "schema"
    logger.warning("Groq output unusable (%s): %.200s", last_error, content)
    return None


def _validate(payload: object) -> dict | None:
    """Validate and normalize the model output. None if unusable."""
    if not isinstance(payload, dict):
        return None
    fatigue = payload.get("fatigue")
    performance = payload.get("performance")
    if not isinstance(fatigue, dict) or not isinstance(performance, dict):
        return None
    if fatigue.get("risk") not in ALLOWED_RISKS:
        return None
    if performance.get("trend") not in ALLOWED_TRENDS:
        return None

    factors = []
    for f in (fatigue.get("factors") or [])[:5]:
        if isinstance(f, dict) and f.get("name"):
            factors.append({
                "name": _clean_str(f["name"], 80),
                "weight": _clamp(f.get("weight"), 0.0, 1.0, 0.5),
            })
    anomalies = []
    for a in (payload.get("anomalies") or [])[:5]:
        if isinstance(a, dict) and a.get("description"):
            sev = a.get("severity")
            anomalies.append({
                "description": _clean_str(a["description"], 300),
                "severity": sev if sev in ALLOWED_SEVERITIES else "normal",
            })
    recommendations = []
    for r in (payload.get("recommendations") or [])[:3]:
        if not isinstance(r, dict) or not r.get("title") or not r.get("body"):
            continue
        cat = r.get("category")
        pri = r.get("priority")
        recommendations.append({
            "category": cat if cat in ALLOWED_REC_CATEGORIES else "general",
            "title": _clean_str(r["title"], 120),
            "body": _clean_str(r["body"], 600),
            "priority": pri if pri in ALLOWED_PRIORITIES else "normal",
        })

    try:
        variation = float(performance.get("variation", 0.0))
        if variation != variation:  # NaN
            variation = 0.0
        variation = max(-1.0, min(1.0, variation))
    except (TypeError, ValueError):
        variation = 0.0

    return {
        "fatigue": {
            "risk": fatigue["risk"],
            "probability": _clamp(fatigue.get("probability"), 0.0, 1.0, 0.5),
            "confidence": _clamp(fatigue.get("confidence"), 0.0, 1.0, 0.5),
            "summary": _clean_str(fatigue.get("summary"), 600),
            "factors": factors,
        },
        "performance": {
            "trend": performance["trend"],
            "variation": round(variation, 3),
            "confidence": _clamp(performance.get("confidence"), 0.0, 1.0, 0.5),
            "summary": _clean_str(performance.get("summary"), 600),
        },
        "anomalies": anomalies,
        "recommendations": recommendations,
    }


def analyze_user(db: Session, user_id: str) -> tuple[dict | None, str]:
    """Run the Groq LLM analysis over the user's rows.

    Returns (validated_result_or_None, data_basis). Never raises: any
    failure (no key, no data, timeout, bad JSON) yields (None, basis).
    """
    if not is_configured():
        logger.info("LLM analysis skipped: GROQ_API_KEY not configured")
        return None, "none"

    evidence, data_basis = build_evidence(db, user_id)
    if evidence is None:
        return None, "none"

    system, user_prompt = _prompt(evidence)
    # Note: no response_format constraint — not all Groq-hosted models
    # support JSON mode, and the parser below already strips fences.
    # The prompt mandates JSON-only output instead.
    # Up to two attempts: formatting flakiness is transient, and a retry
    # is cheaper than showing the user a failure.
    for attempt in (1, 2):
        try:
            resp = requests.post(
                GROQ_API_URL,
                headers={
                    "Authorization": f"Bearer {settings.GROQ_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.GROQ_MODEL,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.3,
                    "max_tokens": settings.GROQ_MAX_TOKENS,
                },
                timeout=settings.GROQ_TIMEOUT_SECONDS,
            )
        except Exception as exc:  # network/timeout: degrade gracefully
            logger.warning("Groq request failed (attempt %d): %s", attempt, type(exc).__name__)
            continue

        if resp.status_code != 200:
            logger.warning("Groq API error (attempt %d): HTTP %s", attempt, resp.status_code)
            continue

        try:
            content = resp.json()["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, AttributeError) as exc:
            logger.warning("Groq envelope unreadable (attempt %d): %s", attempt, type(exc).__name__)
            continue

        result = _parse_response(content)
        if result is not None:
            return result, data_basis
        logger.info("Groq output unusable, retrying (attempt %d)", attempt)

    return None, data_basis
