"""Tests for the Groq LLM analysis layer (HTTP mocked, no real API calls)."""

import json
from datetime import datetime, timezone

import pytest

from app.ai import llm as llm_module
from app.models.ai import FatigueAssessment, PerformancePrediction
from app.models.recommendation import Recommendation
from app.models.self_report import SelfReport
from app.models.session import ActivityMetric, WorkSession
from app.services import ai_service


GROQ_OK = {
    "fatigue": {
        "risk": "moderate",
        "probability": 0.62,
        "confidence": 0.7,
        "summary": "Señales moderadas de fatiga por rachas largas.",
        "factors": [
            {"name": "trabajo continuo", "weight": 0.8},
            {"name": "pausas escasas", "weight": 0.6},
        ],
    },
    "performance": {
        "trend": "stable",
        "variation": 0.05,
        "confidence": 0.6,
        "summary": "Rendimiento estable con ligera tendencia positiva.",
    },
    "anomalies": [{"description": "Pico de inactividad al mediodía.", "severity": "low"}],
    "recommendations": [
        {
            "category": "break",
            "title": "Pausa de 10 minutos",
            "body": "Levántate y descansa la vista.",
            "priority": "normal",
        }
    ],
}


class FakeResp:
    def __init__(self, status_code=200, payload=None, raw=None):
        self.status_code = status_code
        self._payload = payload
        self._raw = raw

    def json(self):
        if self._raw is not None:
            return json.loads(self._raw)
        return self._payload


def _seed_demo_rows(db, user_id):
    now = datetime.now(timezone.utc)
    session = WorkSession(
        user_id=user_id, started_at=now, status="completed", is_demo=True
    )
    db.add(session)
    db.flush()
    db.add_all(
        [
            ActivityMetric(
                session_id=session.id,
                user_id=user_id,
                recorded_at=now,
                interval_seconds=60,
                active_seconds=50,
                idle_seconds=10,
                continuous_work_seconds=300,
                is_demo=True,
            )
            for _ in range(5)
        ]
    )
    db.add(
        SelfReport(
            user_id=user_id,
            session_id=session.id,
            reported_at=now,
            fatigue_level=3,
            stress_level=2,
            concentration_level=4,
            task_difficulty=3,
            perceived_effort=3,
            need_for_break=2,
            is_demo=True,
        )
    )
    db.commit()
    return session


def _fake_ok(*args, **kwargs):
    return FakeResp(
        status_code=200,
        payload={"choices": [{"message": {"content": json.dumps(GROQ_OK)}}]},
    )


def _fake_chatty_ok(*args, **kwargs):
    # Real models often wrap JSON in fences/prose despite instructions.
    body = (
        "Aquí tienes el análisis:\n```json\n"
        + json.dumps(GROQ_OK)
        + "\n```\nEspero que te sea útil."
    )
    return FakeResp(
        status_code=200,
        payload={"choices": [{"message": {"content": body}}]},
    )


@pytest.mark.asyncio
async def test_analyze_success_demo_basis(db, test_user, monkeypatch):
    user, _ = test_user
    monkeypatch.setattr(llm_module.settings, "GROQ_API_KEY", "test-key")
    monkeypatch.setattr(llm_module.requests, "post", _fake_ok)

    _seed_demo_rows(db, user.id)
    result = await ai_service.analyze_with_llm(db, user.id)

    assert result.success is True
    assert result.generated_by == "groq"
    assert result.data_basis == "demo"
    assert result.fatigue["risk_category"] == "moderate"
    assert result.performance["risk_label"] == "moderate_risk"
    assert result.recommendations_created == 1

    assessment = (
        db.query(FatigueAssessment).filter(FatigueAssessment.user_id == user.id).one()
    )
    assert assessment.risk_category == "moderate"
    assert json.loads(assessment.top_features)["_source"] == "groq-llm"
    assert "demostración" in (assessment.comparison_to_baseline or "")

    prediction = (
        db.query(PerformancePrediction)
        .filter(PerformancePrediction.user_id == user.id)
        .one()
    )
    assert prediction.risk_label == "moderate_risk"

    recs = (
        db.query(Recommendation).filter(Recommendation.user_id == user.id).all()
    )
    assert len(recs) == 1
    assert recs[0].status == "pending"


@pytest.mark.asyncio
async def test_analyze_without_key_creates_nothing(db, test_user, monkeypatch):
    user, _ = test_user
    monkeypatch.setattr(llm_module.settings, "GROQ_API_KEY", "")
    _seed_demo_rows(db, user.id)

    result = await ai_service.analyze_with_llm(db, user.id)

    assert result.success is False
    assert "GROQ_API_KEY" in result.message
    assert (
        db.query(FatigueAssessment).filter(FatigueAssessment.user_id == user.id).count()
        == 0
    )


@pytest.mark.asyncio
async def test_analyze_invalid_json_creates_nothing(db, test_user, monkeypatch):
    user, _ = test_user
    monkeypatch.setattr(llm_module.settings, "GROQ_API_KEY", "test-key")
    monkeypatch.setattr(
        llm_module.requests, "post",
        lambda *a, **k: FakeResp(status_code=200, raw="esto no es json {"),
    )
    _seed_demo_rows(db, user.id)

    result = await ai_service.analyze_with_llm(db, user.id)

    assert result.success is False
    assert (
        db.query(FatigueAssessment).filter(FatigueAssessment.user_id == user.id).count()
        == 0
    )


@pytest.mark.asyncio
async def test_analyze_api_error_creates_nothing(db, test_user, monkeypatch):
    user, _ = test_user
    monkeypatch.setattr(llm_module.settings, "GROQ_API_KEY", "test-key")
    monkeypatch.setattr(
        llm_module.requests, "post", lambda *a, **k: FakeResp(status_code=500)
    )
    _seed_demo_rows(db, user.id)

    result = await ai_service.analyze_with_llm(db, user.id)
    assert result.success is False


@pytest.mark.asyncio
async def test_analyze_no_data_at_all(db, test_user, monkeypatch):
    user, _ = test_user
    monkeypatch.setattr(llm_module.settings, "GROQ_API_KEY", "test-key")
    calls = []
    monkeypatch.setattr(
        llm_module.requests, "post",
        lambda *a, **k: (calls.append(1), _fake_ok())[1],
    )

    result = await ai_service.analyze_with_llm(db, user.id)

    assert result.success is False
    assert calls == []  # no billable call without evidence


@pytest.mark.asyncio
async def test_analyze_tolerates_fenced_prose_wrapping(db, test_user, monkeypatch):
    """Real models wrap JSON in fences/prose; the parser must still extract it."""
    user, _ = test_user
    monkeypatch.setattr(llm_module.settings, "GROQ_API_KEY", "test-key")
    monkeypatch.setattr(llm_module.requests, "post", _fake_chatty_ok)
    _seed_demo_rows(db, user.id)

    result = await ai_service.analyze_with_llm(db, user.id)

    assert result.success is True
    assert result.fatigue["risk_category"] == "moderate"
    assert result.performance["risk_label"] == "moderate_risk"


@pytest.mark.asyncio
async def test_analyze_retries_once_after_garbage(db, test_user, monkeypatch):
    """A single malformed reply is retried instead of failing the analysis."""
    user, _ = test_user
    monkeypatch.setattr(llm_module.settings, "GROQ_API_KEY", "test-key")
    calls = []

    def flaky(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            return FakeResp(status_code=200, raw="not json {")
        return _fake_ok(*args, **kwargs)

    monkeypatch.setattr(llm_module.requests, "post", flaky)
    _seed_demo_rows(db, user.id)

    result = await ai_service.analyze_with_llm(db, user.id)

    assert result.success is True
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_analyze_gives_up_after_two_failures(db, test_user, monkeypatch):
    user, _ = test_user
    monkeypatch.setattr(llm_module.settings, "GROQ_API_KEY", "test-key")
    calls = []
    monkeypatch.setattr(
        llm_module.requests, "post",
        lambda *a, **k: (calls.append(1), FakeResp(status_code=200, raw="nope"))[1],
    )
    _seed_demo_rows(db, user.id)

    result = await ai_service.analyze_with_llm(db, user.id)

    assert result.success is False
    assert len(calls) == 2  # one retry, then give up without persisting
    assert (
        db.query(FatigueAssessment).filter(FatigueAssessment.user_id == user.id).count()
        == 0
    )
