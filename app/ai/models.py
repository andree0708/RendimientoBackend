"""Model definitions, training, evaluation, and persistence.

Supports:
- Classification (fatigue risk): LogisticRegression, RandomForest, XGBoost
- Regression (performance variation): RandomForestRegressor, GradientBoosting, XGBoost
- Anomaly detection: IsolationForest

Each trained model is saved with joblib and registered in the model_versions table.
"""

import json
import os
from datetime import datetime, timezone

import joblib
import numpy as np
from sklearn.ensemble import (
    GradientBoostingRegressor,
    IsolationForest,
    RandomForestClassifier,
    RandomForestRegressor,
)
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    mean_absolute_error,
    precision_score,
    r2_score,
    recall_score,
    roc_auc_score,
    root_mean_squared_error,
)
from sklearn.model_selection import GroupKFold, train_test_split
from xgboost import XGBClassifier, XGBRegressor

from app.core.config import settings


# --------------------------------------------------------------------------- #
# Model registry — maps model_type + algorithm to a constructor               #
# --------------------------------------------------------------------------- #

CLASSIFIERS = {
    "logistic_regression": LogisticRegression(max_iter=1000, random_state=42),
    "random_forest": RandomForestClassifier(n_estimators=100, random_state=42),
    "xgboost": XGBClassifier(
        n_estimators=100, max_depth=4, random_state=42, eval_metric="logloss"
    ),
}

REGRESSORS = {
    "random_forest": RandomForestRegressor(n_estimators=100, random_state=42),
    "gradient_boosting": GradientBoostingRegressor(random_state=42),
    "xgboost": XGBRegressor(n_estimators=100, max_depth=4, random_state=42),
}

ANOMALY = {"isolation_forest": IsolationForest(random_state=42, contamination=0.1)}


# --------------------------------------------------------------------------- #
# Training                                                                     #
# --------------------------------------------------------------------------- #


def train_classification(
    X: np.ndarray,
    y: np.ndarray,
    groups: np.ndarray | None = None,
    algorithm: str = "random_forest",
) -> tuple[object, dict]:
    """Train a classification model and return (model, metrics_dict).

    Uses GroupKFold when groups are provided to avoid data leakage across users.
    """
    if algorithm not in CLASSIFIERS:
        raise ValueError(f"Unknown classification algorithm: {algorithm}")

    if groups is not None and len(np.unique(groups)) > 1:
        # Group-aware split: never mix a user's data across train/test
        gkf = GroupKFold(n_splits=min(3, len(np.unique(groups))))
        splits = list(gkf.split(X, y, groups=groups))
        train_idx, test_idx = splits[0]
    else:
        train_idx, test_idx = train_test_split(
            range(len(y)), test_size=0.25, random_state=42, stratify=y if len(np.unique(y)) > 1 else None
        )

    X_train, X_test = X[train_idx], X[test_idx]
    y_train, y_test = y[train_idx], y[test_idx]

    model = CLASSIFIERS[algorithm]
    # Clone to avoid fitting the shared singleton
    from sklearn.base import clone

    model = clone(model)
    model.fit(X_train, y_train)
    y_pred = model.predict(X_test)
    y_proba = model.predict_proba(X_test)[:, 1] if hasattr(model, "predict_proba") else y_pred

    metrics = {
        "algorithm": algorithm,
        "precision": float(precision_score(y_test, y_pred, zero_division=0)),
        "recall": float(recall_score(y_test, y_pred, zero_division=0)),
        "f1_score": float(f1_score(y_test, y_pred, zero_division=0)),
        "accuracy": float(accuracy_score(y_test, y_pred)),
    }
    try:
        metrics["roc_auc"] = float(roc_auc_score(y_test, y_proba))
    except ValueError:
        metrics["roc_auc"] = None

    cm = confusion_matrix(y_test, y_pred).tolist()
    metrics["confusion_matrix"] = cm
    metrics["train_samples"] = len(y_train)
    metrics["test_samples"] = len(y_test)
    return model, metrics


def train_regression(
    X: np.ndarray,
    y: np.ndarray,
    groups: np.ndarray | None = None,
    algorithm: str = "random_forest",
) -> tuple[object, dict]:
    """Train a regression model and return (model, metrics_dict)."""
    if algorithm not in REGRESSORS:
        raise ValueError(f"Unknown regression algorithm: {algorithm}")

    if groups is not None and len(np.unique(groups)) > 1:
        gkf = GroupKFold(n_splits=min(3, len(np.unique(groups))))
        splits = list(gkf.split(X, y, groups=groups))
        train_idx, test_idx = splits[0]
    else:
        train_idx, test_idx = train_test_split(range(len(y)), test_size=0.25, random_state=42)

    X_train, X_test = X[train_idx], X[test_idx]
    y_train, y_test = y[train_idx], y[test_idx]

    from sklearn.base import clone

    model = clone(REGRESSORS[algorithm])
    model.fit(X_train, y_train)
    y_pred = model.predict(X_test)

    metrics = {
        "algorithm": algorithm,
        "mae": float(mean_absolute_error(y_test, y_pred)),
        "rmse": float(root_mean_squared_error(y_test, y_pred)),
        "r2": float(r2_score(y_test, y_pred)),
        "train_samples": len(y_train),
        "test_samples": len(y_test),
    }
    return model, metrics


def train_anomaly(X: np.ndarray, algorithm: str = "isolation_forest") -> tuple[object, dict]:
    """Train an anomaly-detection model (unsupervised)."""
    from sklearn.base import clone

    model = clone(ANOMALY[algorithm])
    model.fit(X)
    metrics = {
        "algorithm": algorithm,
        "train_samples": len(X),
    }
    return model, metrics


def get_feature_importances(model, feature_names: list[str]) -> dict[str, float]:
    """Extract feature importances for explainability."""
    if hasattr(model, "feature_importances_"):
        importances = model.feature_importances_
    elif hasattr(model, "coef_"):
        importances = np.abs(model.coef_[0]) if model.coef_.ndim > 1 else np.abs(model.coef_)
    else:
        return {}

    # Sort by importance, take top 5
    pairs = list(zip(feature_names, importances))
    pairs.sort(key=lambda p: abs(p[1]), reverse=True)
    top = pairs[:5]
    return {name: float(val) for name, val in top}


# --------------------------------------------------------------------------- #
# Persistence                                                                   #
# --------------------------------------------------------------------------- #


def save_model(
    model: object,
    scaler: object | None,
    feature_names: list[str],
    model_type: str,
    algorithm: str,
    metrics: dict,
) -> str:
    """Save a trained model + scaler + metadata to disk and return the file path."""
    os.makedirs(settings.AI_MODELS_DIR, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"{model_type}_{algorithm}_{timestamp}.joblib"
    filepath = os.path.join(settings.AI_MODELS_DIR, filename)

    bundle = {
        "model": model,
        "scaler": scaler,
        "feature_names": feature_names,
        "model_type": model_type,
        "algorithm": algorithm,
        "metrics": metrics,
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }
    joblib.dump(bundle, filepath)
    return filepath


def load_model(filepath: str) -> dict:
    """Load a saved model bundle from disk."""
    return joblib.load(filepath)
