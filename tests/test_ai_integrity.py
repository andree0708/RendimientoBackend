"""Integrity tests for the ML pipeline.

These tests protect against the two failure modes that invalidated the
original results: target leakage and self-reports that never reach training.
"""

from datetime import datetime, timezone

import joblib
import numpy as np
import pandas as pd
from sklearn.datasets import make_classification, make_regression

from app.ai import data_generator, features, models, pipeline
from app.models.ai import ModelVersion


def _engineered_demo():
    metrics_df, reports_df = data_generator.generate_demo_dataset()
    session_features = features.engineer_session_features(metrics_df)
    reports_df = features.link_reports_to_sessions(reports_df, metrics_df)
    session_features = features.add_individual_baseline(
        session_features, causal=True
    )
    return metrics_df, reports_df, session_features


def test_fatigue_features_exclude_self_reports():
    _, reports_df, session_features = _engineered_demo()

    labels = (
        reports_df.dropna(subset=["session_id"])
        .groupby(["user_id", "session_id"], as_index=False)["fatigue_level"]
        .mean()
    )
    labels["fatigue_label"] = (labels["fatigue_level"] >= 3).astype(int)
    session_features = session_features.merge(
        labels[["user_id", "session_id", "fatigue_label"]],
        on=["user_id", "session_id"],
        how="left",
    ).dropna(subset=["fatigue_label"])

    selected = features.select_model_features(
        session_features, "fatigue_classification"
    )
    assert not set(features.SELF_REPORT_COLUMNS) & set(selected.columns)
    assert "fatigue_label" not in selected.columns
    assert len(selected.columns) > 0


def test_performance_features_exclude_target_components():
    _, _, session_features = _engineered_demo()
    session_features["performance_variation"] = (
        session_features["completion_rate"]
        - session_features["error_rate"] * 0.5
        - 0.5
    )
    session_features = features.add_next_session_target(
        session_features,
        "performance_variation",
        "next_performance_variation",
    ).dropna(subset=["next_performance_variation"])

    selected = features.select_model_features(
        session_features, "performance_regression"
    )
    assert not set(features.PERFORMANCE_TARGET_DERIVED_COLUMNS) & set(
        selected.columns
    )
    assert "next_performance_variation" not in selected.columns
    assert "performance_variation" not in selected.columns
    assert len(selected.columns) > 0


def test_report_features_only_use_metrics_before_the_report():
    metrics_df, reports_df = data_generator.generate_demo_dataset()
    report = reports_df.iloc[0]
    window = metrics_df[
        (metrics_df["user_id"] == report["user_id"])
        & (metrics_df["session_id"] == report["session_id"])
        & (metrics_df["recorded_at"] <= report["reported_at"])
    ]

    engineered = features.engineer_report_features(
        metrics_df, reports_df.iloc[[0]]
    )

    assert len(engineered) == 1
    assert engineered.iloc[0]["interval_count"] == len(window)
    # The demo session has 20 intervals and the report is sent at minute 15,
    # so the feature row must not see the last intervals.
    assert engineered.iloc[0]["interval_count"] < 20


def test_reports_without_session_id_are_linked_by_time():
    metrics_df, reports_df = data_generator.generate_demo_dataset()
    original_ids = reports_df["session_id"].copy()
    reports_df["session_id"] = None

    linked = features.link_reports_to_sessions(reports_df, metrics_df)

    assert linked["session_id"].notna().all()
    assert (linked["session_id"] == original_ids).all()


def test_next_session_target_shifts_per_user():
    _, _, session_features = _engineered_demo()
    session_features["performance_variation"] = (
        session_features["completion_rate"]
        - session_features["error_rate"] * 0.5
        - 0.5
    )
    shifted = features.add_next_session_target(
        session_features,
        "performance_variation",
        "next_performance_variation",
    )

    for _, group in shifted.groupby("user_id"):
        group = group.sort_values("session_start")
        assert np.isnan(group["next_performance_variation"].iloc[-1])
        assert (
            group["next_performance_variation"].iloc[:-1].values
            == group["performance_variation"].iloc[1:].values
        ).all()


def test_classification_cv_uses_all_folds_and_compares_algorithms():
    X, y = make_classification(
        n_samples=80,
        n_features=6,
        n_informative=4,
        n_classes=2,
        random_state=42,
    )
    groups = np.repeat(np.arange(8), 10)

    model, metrics = models.train_classification(
        X, y, groups=groups, compare_algorithms=True
    )

    assert model is not None
    assert metrics["cv_folds"] == 5
    assert set(metrics["cv"]) == {
        "logistic_regression",
        "random_forest",
        "xgboost",
    }
    assert metrics["test_samples"] == len(y)
    assert metrics["roc_auc"] is not None


def test_regression_cv_uses_all_folds_and_compares_algorithms():
    X, y = make_regression(
        n_samples=80, n_features=6, noise=0.1, random_state=42
    )
    groups = np.repeat(np.arange(8), 10)

    model, metrics = models.train_regression(
        X, y, groups=groups, compare_algorithms=True
    )

    assert model is not None
    assert metrics["cv_folds"] == 5
    assert set(metrics["cv"]) == {
        "random_forest",
        "gradient_boosting",
        "xgboost",
    }
    assert metrics["test_samples"] == len(y)
    assert metrics["r2"] is not None


def test_legacy_model_bundle_is_rejected_and_deactivated(db, tmp_path):
    """Bundles without the current feature schema must never serve predictions."""
    legacy_path = tmp_path / "legacy.joblib"
    joblib.dump(
        {
            "model": object(),
            "scaler": None,
            "feature_names": ["active_seconds"],
            "model_type": "fatigue_classification",
            "algorithm": "random_forest",
            "metrics": {},
            # No feature_schema_version: this is a pre-fix artefact.
        },
        legacy_path,
    )

    mv = ModelVersion(
        name="legacy_fatigue",
        model_type="fatigue_classification",
        algorithm="random_forest",
        version_tag="legacy",
        file_path=str(legacy_path),
        is_active=True,
        trained_on=datetime.now(timezone.utc),
        samples_used=10,
        notes="legacy bundle",
    )
    db.add(mv)
    db.commit()

    assert pipeline._get_active_model_bundle(db, "fatigue_classification") is None

    db.refresh(mv)
    assert mv.is_active is False


def test_saved_model_records_current_feature_schema(tmp_path, monkeypatch):
    monkeypatch.setattr(models.settings, "AI_MODELS_DIR", str(tmp_path))
    path = models.save_model(
        model=object(),
        scaler=None,
        feature_names=["active_seconds"],
        model_type="fatigue_classification",
        algorithm="random_forest",
        metrics={},
    )

    bundle = models.load_model(path)
    assert bundle["feature_schema_version"] == models.FEATURE_SCHEMA_VERSION


def test_session_features_aggregate_interval_deltas():
    """Per-interval deltas are summed; continuous work is a gauge."""
    df = pd.DataFrame(
        [
            {
                "user_id": "u1",
                "session_id": "s1",
                "recorded_at": "2026-01-01T10:00:00",
                "active_seconds": 50,
                "idle_seconds": 10,
                "continuous_work_seconds": 120,
                "pause_count": 1,
                "pause_total_seconds": 30,
                "app_switch_count": 2,
                "interruptions_count": 0,
                "tasks_started": 2,
                "tasks_completed": 1,
                "errors_reported": 1,
            },
            {
                "user_id": "u1",
                "session_id": "s1",
                "recorded_at": "2026-01-01T10:01:00",
                "active_seconds": 40,
                "idle_seconds": 20,
                "continuous_work_seconds": 300,
                "pause_count": 2,
                "pause_total_seconds": 90,
                "app_switch_count": 3,
                "interruptions_count": 1,
                "tasks_started": 3,
                "tasks_completed": 2,
                "errors_reported": 2,
            },
        ]
    )

    row = features.engineer_session_features(df).iloc[0]

    assert row["total_active_seconds"] == 90
    assert row["total_continuous_work"] == 300
    assert row["total_pause_count"] == 3
    assert row["total_pause_time"] == 120
    assert row["total_app_switches"] == 5
    assert row["total_tasks_completed"] == 3
    assert row["total_errors"] == 3
    assert row["completion_rate"] == 3 / 5


def test_demo_trained_model_is_rejected_for_inference(db, tmp_path):
    """A model trained on synthetic data must never predict on real users."""
    demo_path = tmp_path / "demo.joblib"
    joblib.dump(
        {
            "model": object(),
            "scaler": None,
            "feature_names": ["active_seconds"],
            "model_type": "fatigue_classification",
            "algorithm": "random_forest",
            "metrics": {"is_demo": True},
            "feature_schema_version": models.FEATURE_SCHEMA_VERSION,
        },
        demo_path,
    )

    mv = ModelVersion(
        name="demo_fatigue",
        model_type="fatigue_classification",
        algorithm="random_forest",
        version_tag="demo",
        file_path=str(demo_path),
        is_active=True,
        trained_on=datetime.now(timezone.utc),
        samples_used=100,
        notes="DEMO data: True; activated=True",
    )
    db.add(mv)
    db.commit()

    assert pipeline._get_active_model_bundle(db, "fatigue_classification") is None

    db.refresh(mv)
    assert mv.is_active is False
