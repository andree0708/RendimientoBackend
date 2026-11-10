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
from app.models.session import ActivityMetric
from app.models.self_report import SelfReport
from app.services import recommendation_service
from app.websocket.manager import ws_manager

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Data loading                                                                 #
# --------------------------------------------------------------------------- #


def _load_real_data(db: Session, user_id: str | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load real activity metrics and self-reports from the database."""
    metrics_q = db.query(ActivityMetric)
    reports_q = db.query(SelfReport)

    if user_id:
        metrics_q = metrics_q.filter(ActivityMetric.user_id == user_id)
        reports_q = reports_q.filter(SelfReport.user_id == user_id)

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
        raise ValueError("No data available for training (real or demo)")

    # Engineer session-level features
    session_features = feat_engineering.engineer_session_features(metrics_df)
    session_features = feat_engineering.merge_self_reports(session_features, reports_df)
    session_features = feat_engineering.add_individual_baseline(session_features)

    # Build labels from self-reports
    report_labels = reports_df[["user_id", "session_id", "fatigue_level"]].copy()
    report_labels["fatigue_label"] = (report_labels["fatigue_level"] >= 3).astype(int)
    session_features = session_features.merge(
        report_labels[["user_id", "session_id", "fatigue_label"]],
        on=["user_id", "session_id"],
        how="left",
    )
    session_features["fatigue_label"] = session_features["fatigue_label"].fillna(0).astype(int)

    # Get feature matrix
    drop_cols = ["user_id", "session_id", "fatigue_label"]
    feature_df = session_features.drop(columns=[c for c in drop_cols if c in session_features.columns])
    X, feature_names = feat_engineering.get_feature_matrix(feature_df)
    y = session_features["fatigue_label"].values
    groups = session_features["user_id"].values

    # Train
    algorithm = "random_forest"
    model, metrics = models.train_classification(X, y, groups=groups, algorithm=algorithm)

    # Save model
    scaler = feat_engineering.fit_scaler(X)
    filepath = models.save_model(model, scaler, feature_names, "fatigue_classification", algorithm, metrics)

    # Register in DB
    mv = ModelVersion(
        name="fatigue_classifier",
        model_type="fatigue_classification",
        algorithm=algorithm,
        version_tag=datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"),
        file_path=filepath,
        is_active=True,
        trained_on=datetime.now(timezone.utc),
        samples_used=metrics["train_samples"],
        notes=f"DEMO data: {is_demo}",
    )
    # Deactivate previous active models of same type
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

    Target: performance variation (completion_rate - error_rate * 0.5 - 0.5).
    """
    metrics_df, reports_df, is_demo = _load_or_generate_data(db, user_id, use_demo)

    if metrics_df.empty:
        raise ValueError("No data available for training (real or demo)")

    session_features = feat_engineering.engineer_session_features(metrics_df)
    session_features = feat_engineering.merge_self_reports(session_features, reports_df)
    session_features = feat_engineering.add_individual_baseline(session_features)

    # Build target: performance variation
    # Using the formula from data_generator for consistency
    session_features["performance_variation"] = (
        session_features["completion_rate"] - session_features["error_rate"] * 0.5 - 0.5
    )

    drop_cols = ["user_id", "session_id", "performance_variation"]
    feature_df = session_features.drop(columns=[c for c in drop_cols if c in session_features.columns])
    X, feature_names = feat_engineering.get_feature_matrix(feature_df)
    y = session_features["performance_variation"].values
    groups = session_features["user_id"].values

    algorithm = "gradient_boosting"
    model, metrics = models.train_regression(X, y, groups=groups, algorithm=algorithm)

    scaler = feat_engineering.fit_scaler(X)
    filepath = models.save_model(model, scaler, feature_names, "performance_regression", algorithm, metrics)

    mv = ModelVersion(
        name="performance_predictor",
        model_type="performance_regression",
        algorithm=algorithm,
        version_tag=datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"),
        file_path=filepath,
        is_active=True,
        trained_on=datetime.now(timezone.utc),
        samples_used=metrics["train_samples"],
        notes=f"DEMO data: {is_demo}",
    )
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
        raise ValueError("No data available for training")

    session_features = feat_engineering.engineer_session_features(metrics_df)
    session_features = feat_engineering.add_individual_baseline(session_features)

    drop_cols = ["user_id", "session_id"]
    feature_df = session_features.drop(columns=[c for c in drop_cols if c in session_features.columns])
    X, feature_names = feat_engineering.get_feature_matrix(feature_df)

    model, metrics = models.train_anomaly(X, algorithm="isolation_forest")

    scaler = feat_engineering.fit_scaler(X)
    filepath = models.save_model(model, scaler, feature_names, "anomaly_detection", "isolation_forest", metrics)

    mv = ModelVersion(
        name="anomaly_detector",
        model_type="anomaly_detection",
        algorithm="isolation_forest",
        version_tag=datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"),
        file_path=filepath,
        is_active=True,
        trained_on=datetime.now(timezone.utc),
        samples_used=metrics["train_samples"],
        notes=f"DEMO data: {is_demo}",
    )
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
    """Load the active model of a given type from disk."""
    mv = db.query(ModelVersion).filter(
        ModelVersion.model_type == model_type, ModelVersion.is_active.is_(True)
    ).order_by(ModelVersion.trained_on.desc()).first()
    if not mv:
        return None
    if not os.path.exists(mv.file_path):
        return None
    bundle = models.load_model(mv.file_path)
    bundle["model_version"] = mv
    return bundle


def _build_user_feature_vector(db: Session, user_id: str, session_id: str | None) -> np.ndarray:
    """Build a feature vector for the current user's recent activity."""
    metrics_q = db.query(ActivityMetric).filter(ActivityMetric.user_id == user_id)
    if session_id:
        metrics_q = metrics_q.filter(ActivityMetric.session_id == session_id)

    metrics_list = metrics_q.order_by(ActivityMetric.recorded_at.desc()).limit(100).all()

    if not metrics_list:
        # No real metrics — return zeros; caller will mark prediction as unreliable
        return np.zeros((1, 1)), ["placeholder"]

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
    session_features = feat_engineering.add_individual_baseline(session_features)

    reports = db.query(SelfReport).filter(SelfReport.user_id == user_id).order_by(
        SelfReport.reported_at.desc()
    ).limit(20).all()
    if reports:
        reports_df = pd.DataFrame(
            [
                {
                    "user_id": r.user_id,
                    "session_id": r.session_id,
                    "fatigue_level": r.fatigue_level,
                    "stress_level": r.stress_level,
                    "concentration_level": r.concentration_level,
                    "perceived_effort": r.perceived_effort,
                    "need_for_break": r.need_for_break,
                    "sleep_hours": r.sleep_hours,
                }
                for r in reports
            ]
        )
        session_features = feat_engineering.merge_self_reports(session_features, reports_df)

    drop_cols = ["user_id", "session_id"]
    feature_df = session_features.drop(columns=[c for c in drop_cols if c in session_features.columns])
    X, feature_names = feat_engineering.get_feature_matrix(feature_df)
    return X, feature_names


async def assess_fatigue(db: Session, user_id: str, session_id: str | None) -> FatigueAssessment:
    """Run a fatigue assessment for the user and store the result."""
    bundle = _get_active_model_bundle(db, "fatigue_classification")

    # Determine data availability
    metrics_count = db.query(ActivityMetric).filter(
        ActivityMetric.user_id == user_id
    ).count()

    if bundle is None or metrics_count == 0:
        # No model or no data — return a low-confidence "unknown" assessment
        assessment = FatigueAssessment(
            user_id=user_id,
            session_id=session_id,
            assessed_at=datetime.now(timezone.utc),
            risk_category="unknown",
            risk_probability=0.0,
            confidence=0.0,
            top_features=json.dumps({"note": "No trained model or insufficient data"}),
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

    model = bundle["model"]
    scaler = bundle.get("scaler")
    feature_names = bundle["feature_names"]
    mv = bundle["model_version"]

    X, _ = _build_user_feature_vector(db, user_id, session_id)

    # Align features: the model was trained on a specific set of feature names
    # We need to make sure our feature vector matches
    if X.shape[1] != len(feature_names):
        # Feature mismatch — create a padded/aligned vector
        padded = np.zeros((1, len(feature_names)))
        min_cols = min(X.shape[1], len(feature_names))
        padded[0, :min_cols] = X[0, :min_cols] if X.ndim > 1 else X[:min_cols]
        X = padded

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

    confidence = risk_probability if prediction == 1 else (1 - risk_probability)

    # Explainability
    top_features = models.get_feature_importances(model, feature_names)

    assessment = FatigueAssessment(
        user_id=user_id,
        session_id=session_id,
        assessed_at=datetime.now(timezone.utc),
        risk_category=risk_category,
        risk_probability=risk_probability,
        confidence=round(confidence, 3),
        top_features=json.dumps(top_features),
        comparison_to_baseline="Compared to your historical average",
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
        ActivityMetric.user_id == user_id
    ).count()

    if bundle is None or metrics_count == 0:
        prediction = PerformancePrediction(
            user_id=user_id,
            session_id=session_id,
            predicted_at=datetime.now(timezone.utc),
            target_time=datetime.now(timezone.utc) + timedelta(minutes=settings.AI_PREDICTION_HORIZON_MINUTES),
            predicted_variation=0.0,
            risk_label="unknown",
            horizon_minutes=settings.AI_PREDICTION_HORIZON_MINUTES,
            confidence=0.0,
            top_features=json.dumps({"note": "No trained model or insufficient data"}),
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

    model = bundle["model"]
    scaler = bundle.get("scaler")
    feature_names = bundle["feature_names"]
    mv = bundle["model_version"]

    X, _ = _build_user_feature_vector(db, user_id, session_id)

    if X.shape[1] != len(feature_names):
        padded = np.zeros((1, len(feature_names)))
        min_cols = min(X.shape[1], len(feature_names))
        padded[0, :min_cols] = X[0, :min_cols] if X.ndim > 1 else X[:min_cols]
        X = padded

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

    prediction = PerformancePrediction(
        user_id=user_id,
        session_id=session_id,
        predicted_at=datetime.now(timezone.utc),
        target_time=datetime.now(timezone.utc) + timedelta(minutes=settings.AI_PREDICTION_HORIZON_MINUTES),
        predicted_variation=round(variation, 4),
        risk_label=risk_label,
        horizon_minutes=settings.AI_PREDICTION_HORIZON_MINUTES,
        confidence=round(abs(variation), 3),
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

    X, _ = _build_user_feature_vector(db, user_id, None)

    # Align features: pad or select to match the model's expected input
    if X.shape[1] != len(feature_names):
        padded = np.zeros((1, len(feature_names)))
        min_cols = min(X.shape[1], len(feature_names))
        padded[0, :min_cols] = X[0, :min_cols] if X.ndim > 1 else X[:min_cols]
        X = padded

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
        raise ValueError(f"Unknown model type: {model_type}")

    return {
        "model_version_id": mv.id,
        "model_type": mv.model_type,
        "algorithm": mv.algorithm,
        "version_tag": mv.version_tag,
        "metrics": metrics,
        "demo_data": "DEMO" in (mv.notes or ""),
    }
