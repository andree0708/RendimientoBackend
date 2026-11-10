"""End-to-end AI pipeline orchestration.

Coordinates data loading/generation, feature engineering, training, and
inference for:
A. Fatigue assessment (classification on self-report labels)
B. Performance prediction (regression on task-metric labels)
C. Anomaly detection (unsupervised)
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from app.ai import data_generator, features as feat_engineering, models
from app.core.config import settings
from app.models.ai import (
    FatigueAssessment,
    ModelEvaluation,
    ModelVersion,
    PerformancePrediction,
)
from app.models.session import ActivityMetric, WorkSession
from app.models.self_report import SelfReport
from app.services import recommendation_service
from app.websocket.manager import ws_manager

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Data loading                                                                 #
# --------------------------------------------------------------------------- #


def _load_real_data(db: Session, user_id: str | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load real activity metrics and self-reports from the database.

    Rows seeded for demonstration (``is_demo=True``) are excluded so a
    model trained on this data can never learn from synthetic examples.
    """
    metrics_q = db.query(ActivityMetric).filter(ActivityMetric.is_demo.is_(False))
    reports_q = db.query(SelfReport).filter(SelfReport.is_demo.is_(False))

    if user_id:
        metrics_q = metrics_q.filter(ActivityMetric.user_id == user_id)
        reports_q = reports_q.filter(SelfReport.user_id == user_id)

    # Defence in depth: also drop rows attached to a demo session, in case
    # only the parent was flagged.
    demo_sq = db.query(WorkSession.id).filter(WorkSession.is_demo.is_(True))
    if user_id:
        demo_sq = demo_sq.filter(WorkSession.user_id == user_id)
    demo_session_ids = [row[0] for row in demo_sq.all()]
    if demo_session_ids:
        metrics_q = metrics_q.filter(~ActivityMetric.session_id.in_(demo_session_ids))
        reports_q = reports_q.filter(
            (SelfReport.session_id.is_(None))
            | (~SelfReport.session_id.in_(demo_session_ids))
        )

    metrics_list = metrics_q.all()
    reports_list = reports_q.all()

    if len(metrics_list) < settings.AI_MIN_SAMPLES_FOR_TRAINING:
        return pd.DataFrame(), pd.DataFrame()

    metrics_df = pd.DataFrame(
        [
            {
                "user_id": m.user_id,
                "session_id": m.session_id,
                "recorded_at": m.recorded_at,
                "active_seconds": m.active_seconds,
                "idle_seconds": m.idle_seconds,
                "continuous_work_seconds": m.continuous_work_seconds,
                "pause_count": m.pause_count,
                "pause_total_seconds": m.pause_total_seconds,
                "app_switch_count": m.app_switch_count,
                "interruptions_count": m.interruptions_count,
                "tasks_started": m.tasks_started,
                "tasks_completed": m.tasks_completed,
                "errors_reported": m.errors_reported,
                "is_demo": False,
            }
            for m in metrics_list
        ]
    )

    reports_df = pd.DataFrame(
        [
            {
                "user_id": r.user_id,
                "session_id": r.session_id,
                "reported_at": r.reported_at,
                "fatigue_level": r.fatigue_level,
                "stress_level": r.stress_level,
                "concentration_level": r.concentration_level,
                "task_difficulty": r.task_difficulty,
                "perceived_effort": r.perceived_effort,
                "need_for_break": r.need_for_break,
                "sleep_hours": r.sleep_hours,
                "sleep_quality": r.sleep_quality,
                "rest_quality_previous_night": r.rest_quality_previous_night,
                "is_demo": False,
            }
            for r in reports_list
        ]
    )

    return metrics_df, reports_df


def _load_or_generate_data(db: Session, user_id: str | None, use_demo: bool) -> tuple[pd.DataFrame, pd.DataFrame, bool]:
    """Load real data; fall back to demo data if insufficient and use_demo=True."""
    metrics_df, reports_df = _load_real_data(db, user_id)

    if not metrics_df.empty and len(metrics_df) >= settings.AI_MIN_SAMPLES_FOR_TRAINING:
        return metrics_df, reports_df, False

    if not use_demo:
        return metrics_df, reports_df, False

    logger.info("Insufficient real data (%d samples). Generating DEMO data.", len(metrics_df))
    demo_metrics, demo_reports = data_generator.generate_demo_dataset()
    return demo_metrics, demo_reports, True


# --------------------------------------------------------------------------- #
# Training                                                                      #
# --------------------------------------------------------------------------- #


async def train_fatigue_model(
    db: Session, user_id: str | None, use_demo: bool
) -> tuple[ModelVersion, dict]:
    """Train a fatigue classification model.

    Target: binary label from self-report fatigue_level >= threshold.
    """
    metrics_df, reports_df, is_demo = _load_or_generate_data(db, user_id, use_demo)

    if metrics_df.empty:
        raise ValueError("No hay datos disponibles para entrenar (reales o demo)")

    # Build one row per self-report using only activity observed *before* the
    # report. Self-reports are labels, never features. Older clients sent no
    # session_id, so link those reports by time first.
    reports_df = feat_engineering.link_reports_to_sessions(reports_df, metrics_df)
    session_features = feat_engineering.engineer_report_features(
        metrics_df, reports_df
    )
    if session_features.empty:
        raise ValueError(
            "No hay autorreportes con actividad previa disponibles. Envía autorreportes "
            "durante una sesión para crear etiquetas de entrenamiento."
        )
    session_features = feat_engineering.add_individual_baseline(
        session_features, causal=True
    )

    # Explicit feature selection prevents target leakage.
    feature_df = feat_engineering.select_model_features(
        session_features, "fatigue_classification"
    )
    feature_names = feature_df.columns.tolist()
    X = feature_df.values
    y = session_features["fatigue_label"].values
    groups = session_features["user_id"].values

    # Train (cross-validation compares algorithms and selects the best one)
    model, metrics = models.train_classification(
        X, y, groups=groups, algorithm="random_forest"
    )
    algorithm = metrics["algorithm"]

    # Quality gate: a model that only predicts the majority class must not be
    # activated, even if its ROC-AUC looks acceptable.
    reliable = (
        metrics.get("roc_auc") is not None
        and metrics["roc_auc"] >= settings.AI_MIN_ROC_AUC
        and (metrics.get("balanced_accuracy") or 0.0)
        >= settings.AI_MIN_BALANCED_ACCURACY
    )
    metrics["reliable"] = reliable
    # Models trained on synthetic data are kept for audit/evaluation only.
    # They must never drive predictions about real users.
    activation_allowed = reliable and not is_demo
    metrics["is_demo"] = is_demo
    metrics["activated"] = activation_allowed

    # Save model
    # Scaling is handled inside the model pipeline when needed.
    scaler = None
    filepath = models.save_model(model, scaler, feature_names, "fatigue_classification", algorithm, metrics)

    # Register in DB
    mv = ModelVersion(
        name="fatigue_classifier",
        model_type="fatigue_classification",
        algorithm=algorithm,
        version_tag=datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"),
        file_path=filepath,
        is_active=activation_allowed,
        trained_on=datetime.now(timezone.utc),
        samples_used=metrics["train_samples"],
        notes=(
            f"DEMO data: {is_demo}; "
            f"activated={activation_allowed}; "
            f"{metrics.get('cv_folds', 1)}-fold group CV; "
            f"selected by {metrics.get('selected_by', 'holdout')}; "
            f"reliable={reliable} (min ROC-AUC {settings.AI_MIN_ROC_AUC}, "
            f"min balanced accuracy {settings.AI_MIN_BALANCED_ACCURACY}); "
            f"feature schema v{models.FEATURE_SCHEMA_VERSION}"
        ),
    )
    # Only replace the active model when the new one passes the quality gate
    # and was trained on real data.
    if activation_allowed:
        db.query(ModelVersion).filter(
            ModelVersion.model_type == "fatigue_classification", ModelVersion.is_active.is_(True)
        ).update({"is_active": False})
    db.add(mv)
    db.flush()

    # Store evaluation metrics
    eval_record = ModelEvaluation(
        model_version_id=mv.id,
        precision=metrics.get("precision"),
        recall=metrics.get("recall"),
        f1_score=metrics.get("f1_score"),
        roc_auc=metrics.get("roc_auc"),
        confusion_matrix=json.dumps(metrics.get("confusion_matrix")),
    )
    db.add(eval_record)
    db.commit()
    db.refresh(mv)

    # Notify via WebSocket
    await ws_manager.broadcast(
        "model.status_changed",
        {"model_type": "fatigue_classification", "version": mv.version_tag, "status": "trained"},
    )

    return mv, metrics


async def train_performance_model(
    db: Session, user_id: str | None, use_demo: bool
) -> tuple[ModelVersion, dict]:
    """Train a performance regression model.

    Target: performance variation of the NEXT session for the same user,
    built as ``completion_rate - error_rate * 0.5 - 0.5``.
    """
    metrics_df, reports_df, is_demo = _load_or_generate_data(db, user_id, use_demo)

    if metrics_df.empty:
        raise ValueError("No hay datos disponibles para entrenar (reales o demo)")

    session_features = feat_engineering.engineer_session_features(metrics_df)
    session_features = feat_engineering.add_individual_baseline(
        session_features, causal=True
    )

    # Target: performance variation of the NEXT session (future window).
    # This matches the spec's forecast horizon and avoids predicting the
    # present from the present.
    session_features["performance_variation"] = (
        session_features["completion_rate"] - session_features["error_rate"] * 0.5 - 0.5
    )
    session_features = feat_engineering.add_next_session_target(
        session_features,
        "performance_variation",
        "next_performance_variation",
    )
    session_features = session_features.dropna(
        subset=["next_performance_variation"]
    )
    if session_features.empty:
        raise ValueError(
            "La predicción de rendimiento necesita al menos dos sesiones por usuario."
        )

    # Explicit feature selection excludes the target's own components
    # (completion_rate, error_rate and their aggregates) and the target itself.
    feature_df = feat_engineering.select_model_features(
        session_features, "performance_regression"
    )
    feature_names = feature_df.columns.tolist()
    X = feature_df.values
    y = session_features["next_performance_variation"].values
    groups = session_features["user_id"].values

    model, metrics = models.train_regression(
        X, y, groups=groups, algorithm="gradient_boosting"
    )
    algorithm = metrics["algorithm"]

    # Quality gate: negative R² means the model is worse than predicting the
    # mean, so it must not be activated.
    reliable = (
        metrics.get("r2") is not None and metrics["r2"] >= settings.AI_MIN_R2
    )
    metrics["reliable"] = reliable
    activation_allowed = reliable and not is_demo
    metrics["is_demo"] = is_demo
    metrics["activated"] = activation_allowed

    # Scaling is handled inside the model pipeline when needed.
    scaler = None
    filepath = models.save_model(model, scaler, feature_names, "performance_regression", algorithm, metrics)

    mv = ModelVersion(
        name="performance_predictor",
        model_type="performance_regression",
        algorithm=algorithm,
        version_tag=datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"),
        file_path=filepath,
        is_active=activation_allowed,
        trained_on=datetime.now(timezone.utc),
        samples_used=metrics["train_samples"],
        notes=(
            f"DEMO data: {is_demo}; "
            f"activated={activation_allowed}; "
            f"{metrics.get('cv_folds', 1)}-fold group CV; "
            f"selected by {metrics.get('selected_by', 'holdout')}; "
            f"reliable={reliable} (min R2 {settings.AI_MIN_R2}); "
            f"feature schema v{models.FEATURE_SCHEMA_VERSION}"
        ),
    )
    if activation_allowed:
        db.query(ModelVersion).filter(
            ModelVersion.model_type == "performance_regression", ModelVersion.is_active.is_(True)
        ).update({"is_active": False})
    db.add(mv)
    db.flush()

    eval_record = ModelEvaluation(
        model_version_id=mv.id,
        mae=metrics.get("mae"),
        rmse=metrics.get("rmse"),
        r2=metrics.get("r2"),
    )
    db.add(eval_record)
    db.commit()
    db.refresh(mv)

    await ws_manager.broadcast(
        "model.status_changed",
        {"model_type": "performance_regression", "version": mv.version_tag, "status": "trained"},
    )

    return mv, metrics


async def train_anomaly_model(
    db: Session, user_id: str | None, use_demo: bool
) -> tuple[ModelVersion, dict]:
    """Train an anomaly-detection model (Isolation Forest)."""
    metrics_df, _, is_demo = _load_or_generate_data(db, user_id, use_demo)

    if metrics_df.empty:
        raise ValueError("No hay datos disponibles para entrenar")

    session_features = feat_engineering.engineer_session_features(metrics_df)
    session_features = feat_engineering.add_individual_baseline(
        session_features, causal=True
    )

    feature_df = feat_engineering.select_model_features(
        session_features, "anomaly_detection"
    )
    feature_names = feature_df.columns.tolist()
    X = feature_df.values

    model, metrics = models.train_anomaly(X, algorithm="isolation_forest")

    # Quality gate for anomaly detection (unsupervised, no ROC/R2 available):
    # synthetic data never activates, and real data needs a minimum number
    # of sessions to avoid flagging normal behaviour from noise.
    min_samples = settings.AI_MIN_SAMPLES_FOR_TRAINING
    enough_data = metrics.get("train_samples", 0) >= min_samples
    activation_allowed = not is_demo and enough_data
    metrics["is_demo"] = is_demo
    metrics["activated"] = activation_allowed
    metrics["reliable"] = enough_data
    metrics["min_samples"] = min_samples

    # Scaling is handled inside the model pipeline when needed.
    scaler = None
    filepath = models.save_model(model, scaler, feature_names, "anomaly_detection", "isolation_forest", metrics)

    mv = ModelVersion(
        name="anomaly_detector",
        model_type="anomaly_detection",
        algorithm="isolation_forest",
        version_tag=datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"),
        file_path=filepath,
        is_active=activation_allowed,
        trained_on=datetime.now(timezone.utc),
        samples_used=metrics["train_samples"],
        notes=(
            f"DEMO data: {is_demo}; "
            f"activated={activation_allowed}; "
            f"samples={metrics['train_samples']}/{min_samples}; "
            f"feature schema v{models.FEATURE_SCHEMA_VERSION}"
        ),
    )
    if activation_allowed:
        db.query(ModelVersion).filter(
            ModelVersion.model_type == "anomaly_detection", ModelVersion.is_active.is_(True)
        ).update({"is_active": False})
    db.add(mv)
    db.commit()
    db.refresh(mv)

    return mv, metrics


# --------------------------------------------------------------------------- #
# Inference                                                                     #
# --------------------------------------------------------------------------- #


def _get_active_model_bundle(db: Session, model_type: str) -> dict | None:
    """Load the active model of a given type from disk.

    Only artefacts produced with the current feature schema are accepted.
    Legacy bundles (e.g. trained before the target-leakage fix) are
    deactivated instead of being used for predictions.
    """
    mv = db.query(ModelVersion).filter(
        ModelVersion.model_type == model_type, ModelVersion.is_active.is_(True)
    ).order_by(ModelVersion.trained_on.desc()).first()
    if not mv:
        return None
    if not os.path.exists(mv.file_path):
        logger.warning("Active model %s file is missing: %s", mv.id, mv.file_path)
        mv.is_active = False
        db.commit()
        return None

    bundle = models.load_model(mv.file_path)
    if bundle.get("feature_schema_version") != models.FEATURE_SCHEMA_VERSION:
        logger.warning(
            "Deactivating legacy model %s (%s): feature schema %s != %s",
            mv.id,
            mv.file_path,
            bundle.get("feature_schema_version"),
            models.FEATURE_SCHEMA_VERSION,
        )
        mv.is_active = False
        db.commit()
        return None

    # Defence in depth: a model trained on synthetic data must never produce
    # predictions about real users, even if it was mistakenly activated.
    trained_on_demo = bool(bundle.get("metrics", {}).get("is_demo")) or (
        "DEMO data: True" in (mv.notes or "")
    )
    if trained_on_demo:
        logger.warning(
            "Deactivating model %s: it was trained on synthetic demo data", mv.id
        )
        mv.is_active = False
        db.commit()
        return None

    bundle["model_version"] = mv
    return bundle


def _build_user_feature_frame(
    db: Session, user_id: str, session_id: str | None
) -> pd.DataFrame:
    """Build engineered features for the requested session (or the latest one).

    All of the user's sessions are loaded so the individual baseline can be
    computed from history. Self-reports are not merged here: they are labels,
    not predictors.
    """
    metrics_list = (
        db.query(ActivityMetric)
        .filter(ActivityMetric.user_id == user_id)
        .filter(ActivityMetric.is_demo.is_(False))
        .order_by(ActivityMetric.recorded_at.asc())
        .all()
    )
    if not metrics_list:
        return pd.DataFrame()

    metrics_df = pd.DataFrame(
        [
            {
                "user_id": m.user_id,
                "session_id": m.session_id,
                "recorded_at": m.recorded_at,
                "active_seconds": m.active_seconds,
                "idle_seconds": m.idle_seconds,
                "continuous_work_seconds": m.continuous_work_seconds,
                "pause_count": m.pause_count,
                "pause_total_seconds": m.pause_total_seconds,
                "app_switch_count": m.app_switch_count,
                "interruptions_count": m.interruptions_count,
                "tasks_started": m.tasks_started,
                "tasks_completed": m.tasks_completed,
                "errors_reported": m.errors_reported,
            }
            for m in metrics_list
        ]
    )

    session_features = feat_engineering.engineer_session_features(metrics_df)
    session_features = feat_engineering.add_individual_baseline(
        session_features, causal=True
    )

    if session_id:
        return session_features[session_features["session_id"] == session_id]

    latest_session = metrics_df.sort_values("recorded_at")["session_id"].iloc[-1]
    return session_features[session_features["session_id"] == latest_session]


async def assess_fatigue(db: Session, user_id: str, session_id: str | None) -> FatigueAssessment:
    """Run a fatigue assessment for the user and store the result."""
    bundle = _get_active_model_bundle(db, "fatigue_classification")

    # Determine data availability (real rows only; demo seed doesn't count)
    metrics_count = db.query(ActivityMetric).filter(
        ActivityMetric.user_id == user_id,
        ActivityMetric.is_demo.is_(False),
    ).count()

    if bundle is None:
        # No trained model at all — return unknown
        assessment = FatigueAssessment(
            user_id=user_id,
            session_id=session_id,
            assessed_at=datetime.now(timezone.utc),
            risk_category="unknown",
            risk_probability=0.0,
            confidence=0.0,
            top_features=json.dumps({"note": "No trained model available. Train a model first from the Admin panel."}),
            comparison_to_baseline="No baseline available yet",
        )
        db.add(assessment)
        db.commit()
        db.refresh(assessment)
        await ws_manager.send_to_user(
            user_id, "fatigue.risk_updated",
            {"assessment_id": assessment.id, "risk_category": "unknown", "confidence": 0.0},
            session_id=session_id,
        )
        return assessment

    # If no personal data yet, use a neutral/baseline feature vector
    # and flag it as low confidence (the system is learning)
    insufficient_data = metrics_count == 0

    model = bundle["model"]
    scaler = bundle.get("scaler")
    feature_names = bundle["feature_names"]
    mv = bundle["model_version"]

    feature_frame = _build_user_feature_frame(db, user_id, session_id)

    # If no personal data: use a zero/neutral vector. Confidence will be low.
    if insufficient_data or feature_frame.empty:
        X = np.zeros((1, len(feature_names)))
        insufficient_data = True
    else:
        X = feat_engineering.align_feature_matrix(feature_frame, feature_names)

    if scaler:
        X = scaler.transform(X)

    prediction = model.predict(X)[0]
    if hasattr(model, "predict_proba"):
        proba = model.predict_proba(X)[0]
        risk_probability = float(proba[1]) if len(proba) > 1 else float(prediction)
    else:
        risk_probability = float(prediction)

    # Map to risk category
    if risk_probability >= 0.7:
        risk_category = "high"
    elif risk_probability >= 0.4:
        risk_category = "moderate"
    else:
        risk_category = "low"

    # Cap confidence when data is insufficient
    raw_confidence = risk_probability if prediction == 1 else (1 - risk_probability)
    confidence = round(raw_confidence * 0.3, 3) if insufficient_data else round(raw_confidence, 3)

    # Explainability
    top_features = models.get_feature_importances(model, feature_names)

    comparison = (
        "Initial estimate — more activity data needed to personalize this result."
        if insufficient_data
        else "Compared to your individual historical baseline."
    )

    assessment = FatigueAssessment(
        user_id=user_id,
        session_id=session_id,
        assessed_at=datetime.now(timezone.utc),
        risk_category=risk_category,
        risk_probability=round(risk_probability, 4),
        confidence=confidence,
        top_features=json.dumps(top_features),
        comparison_to_baseline=comparison,
        model_version_id=mv.id,
    )
    db.add(assessment)
    db.commit()
    db.refresh(assessment)

    await ws_manager.send_to_user(
        user_id, "fatigue.risk_updated",
        {
            "assessment_id": assessment.id,
            "risk_category": risk_category,
            "risk_probability": round(risk_probability, 3),
            "confidence": round(confidence, 3),
        },
        session_id=session_id,
    )

    # Generate recommendation if risk is moderate or high
    if risk_category in ("moderate", "high"):
        await recommendation_service.create_and_push(
            db=db,
            user_id=user_id,
            category="break",
            title="Consider a brief break",
            body="Recent patterns suggest signs of fatigue. A short pause could help maintain your performance.",
            reason=f"Fatigue risk estimated at {risk_probability:.0%}. Key factors: {', '.join(list(top_features.keys())[:3])}.",
            session_id=session_id,
            priority="high" if risk_category == "high" else "normal",
        )

    return assessment


async def predict_performance(db: Session, user_id: str, session_id: str | None) -> PerformancePrediction:
    """Run a performance prediction for the user and store the result."""
    bundle = _get_active_model_bundle(db, "performance_regression")

    metrics_count = db.query(ActivityMetric).filter(
        ActivityMetric.user_id == user_id,
        ActivityMetric.is_demo.is_(False),
    ).count()

    if bundle is None:
        prediction = PerformancePrediction(
            user_id=user_id,
            session_id=session_id,
            predicted_at=datetime.now(timezone.utc),
            target_time=datetime.now(timezone.utc) + timedelta(minutes=settings.AI_PREDICTION_HORIZON_MINUTES),
            predicted_variation=0.0,
            risk_label="unknown",
            horizon_minutes=settings.AI_PREDICTION_HORIZON_MINUTES,
            confidence=0.0,
            top_features=json.dumps({"note": "No trained model available. Train a model first from the Admin panel."}),
        )
        db.add(prediction)
        db.commit()
        db.refresh(prediction)
        await ws_manager.send_to_user(
            user_id, "performance.forecast_updated",
            {"prediction_id": prediction.id, "risk_label": "unknown", "confidence": 0.0},
            session_id=session_id,
        )
        return prediction

    insufficient_data = metrics_count == 0

    model = bundle["model"]
    scaler = bundle.get("scaler")
    feature_names = bundle["feature_names"]
    mv = bundle["model_version"]

    feature_frame = _build_user_feature_frame(db, user_id, session_id)

    # If no personal data: use a neutral/baseline zero vector
    if insufficient_data or feature_frame.empty:
        X = np.zeros((1, len(feature_names)))
        insufficient_data = True
    else:
        X = feat_engineering.align_feature_matrix(feature_frame, feature_names)

    if scaler:
        X = scaler.transform(X)

    variation = float(model.predict(X)[0])

    if variation <= -0.2:
        risk_label = "high_risk"
    elif variation <= 0:
        risk_label = "moderate_risk"
    else:
        risk_label = "low_risk"

    top_features = models.get_feature_importances(model, feature_names)
    # Cap confidence when data is insufficient
    raw_confidence = round(abs(variation), 3)
    confidence = round(raw_confidence * 0.3, 3) if insufficient_data else raw_confidence

    prediction = PerformancePrediction(
        user_id=user_id,
        session_id=session_id,
        predicted_at=datetime.now(timezone.utc),
        target_time=datetime.now(timezone.utc) + timedelta(minutes=settings.AI_PREDICTION_HORIZON_MINUTES),
        predicted_variation=round(variation, 4),
        risk_label=risk_label,
        horizon_minutes=settings.AI_PREDICTION_HORIZON_MINUTES,
        confidence=confidence,
        top_features=json.dumps(top_features),
        model_version_id=mv.id,
    )
    db.add(prediction)
    db.commit()
    db.refresh(prediction)

    await ws_manager.send_to_user(
        user_id, "performance.forecast_updated",
        {
            "prediction_id": prediction.id,
            "predicted_variation": round(variation, 4),
            "risk_label": risk_label,
        },
        session_id=session_id,
    )

    return prediction


def detect_anomalies(db: Session, user_id: str) -> dict:
    """Run anomaly detection for the user's recent activity."""
    bundle = _get_active_model_bundle(db, "anomaly_detection")

    if bundle is None:
        return {"anomalies": [], "note": "No trained anomaly detection model"}

    model = bundle["model"]
    scaler = bundle.get("scaler")
    feature_names = bundle["feature_names"]

    feature_frame = _build_user_feature_frame(db, user_id, None)
    if feature_frame.empty:
        return {"anomalies": [], "note": "No activity data available"}
    X = feat_engineering.align_feature_matrix(feature_frame, feature_names)

    if scaler:
        X = scaler.transform(X)

    predictions = model.predict(X)
    # IsolationForest: -1 = anomaly, 1 = normal
    anomaly_indices = np.where(predictions == -1)[0]
    return {
        "anomaly_count": int(len(anomaly_indices)),
        "is_anomalous": int(len(anomaly_indices)) > 0,
        "anomaly_score": float(np.mean(model.decision_function(X)) if hasattr(model, "decision_function") else 0),
    }


# --------------------------------------------------------------------------- #
# High-level training dispatch                                                  #
# --------------------------------------------------------------------------- #


async def train_pipeline(db: Session, model_type: str, user_id: str | None, use_demo: bool) -> dict:
    """Dispatch training to the appropriate pipeline based on model_type."""
    if model_type == "fatigue_classification":
        mv, metrics = await train_fatigue_model(db, user_id, use_demo)
    elif model_type == "performance_regression":
        mv, metrics = await train_performance_model(db, user_id, use_demo)
    elif model_type == "anomaly_detection":
        mv, metrics = await train_anomaly_model(db, user_id, use_demo)
    else:
        raise ValueError(f"Tipo de modelo desconocido: {model_type}")

    return {
        "model_version_id": mv.id,
        "model_type": mv.model_type,
        "algorithm": mv.algorithm,
        "version_tag": mv.version_tag,
        "metrics": metrics,
        "reliable": bool(metrics.get("reliable", True)),
        "demo_data": bool(metrics.get("is_demo", False)),
        "activated": bool(metrics.get("activated", mv.is_active)),
    }
