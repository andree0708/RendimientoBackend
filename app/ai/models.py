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
    balanced_accuracy_score,
    confusion_matrix,
    f1_score,
    mean_absolute_error,
    precision_score,
    r2_score,
    recall_score,
    roc_auc_score,
    root_mean_squared_error,
)
from sklearn.model_selection import GroupKFold, KFold, StratifiedKFold, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier, XGBRegressor

from app.core.config import settings


# --------------------------------------------------------------------------- #
# Model registry — maps model_type + algorithm to a constructor               #
# --------------------------------------------------------------------------- #

CLASSIFIERS = {
    # Scaling lives inside the model so training and inference always use the
    # same transformation. Tree models do not need it.
    "logistic_regression": Pipeline(
        [
            ("scaler", StandardScaler()),
            ("model", LogisticRegression(max_iter=1000, random_state=42)),
        ]
    ),
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


def _make_splits(
    X: np.ndarray,
    y: np.ndarray,
    groups: np.ndarray | None,
    task: str,
) -> tuple[list[tuple[np.ndarray, np.ndarray]], int]:
    """Build cross-validation splits that never mix users across folds."""
    n_samples = len(y)

    if groups is not None and len(np.unique(groups)) > 1:
        n_splits = min(5, len(np.unique(groups)))
        return (
            list(GroupKFold(n_splits=n_splits).split(X, y, groups=groups)),
            n_splits,
        )

    if task == "classification":
        _, class_counts = np.unique(y, return_counts=True)
        n_splits = min(5, int(class_counts.min())) if len(class_counts) else 0
        if n_splits >= 2:
            splitter = StratifiedKFold(
                n_splits=n_splits, shuffle=True, random_state=42
            )
            return list(splitter.split(X, y)), n_splits
    else:
        n_splits = min(5, n_samples)
        if n_splits >= 2:
            splitter = KFold(n_splits=n_splits, shuffle=True, random_state=42)
            return list(splitter.split(X, y)), n_splits

    # Last-resort holdout for very small datasets.
    train_idx, test_idx = train_test_split(
        np.arange(n_samples),
        test_size=0.25,
        random_state=42,
        stratify=y if task == "classification" and len(np.unique(y)) > 1 else None,
    )
    return [(train_idx, test_idx)], 1


def _classification_fold_metrics(
    y_true: np.ndarray, y_pred: np.ndarray, y_proba: np.ndarray
) -> dict:
    metrics = {
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1_score": float(f1_score(y_true, y_pred, zero_division=0)),
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "balanced_accuracy": float(balanced_accuracy_score(y_true, y_pred)),
    }
    try:
        metrics["roc_auc"] = float(roc_auc_score(y_true, y_proba))
    except ValueError:
        metrics["roc_auc"] = None
    return metrics


def _aggregate_folds(fold_metrics: list[dict]) -> tuple[dict, dict]:
    """Return (mean, std) for every metric across folds, ignoring None."""
    mean: dict = {}
    std: dict = {}
    if not fold_metrics:
        return mean, std
    for key in fold_metrics[0]:
        values = [m[key] for m in fold_metrics if m.get(key) is not None]
        mean[key] = float(np.mean(values)) if values else None
        std[key] = float(np.std(values)) if values else None
    return mean, std


def train_classification(
    X: np.ndarray,
    y: np.ndarray,
    groups: np.ndarray | None = None,
    algorithm: str = "random_forest",
    compare_algorithms: bool = True,
) -> tuple[object, dict]:
    """Train a classification model and return (model, metrics_dict).

    Every fold of a group-aware cross-validation is evaluated. When
    ``compare_algorithms`` is True, all registered classifiers are compared
    and the one with the best mean CV ROC-AUC (tie-broken by balanced
    accuracy and F1) is refit on the full dataset.
    """
    if algorithm not in CLASSIFIERS:
        raise ValueError(f"Unknown classification algorithm: {algorithm}")
    if len(np.unique(y)) < 2:
        raise ValueError("Classification requires at least two classes")

    from sklearn.base import clone

    candidates = list(CLASSIFIERS) if compare_algorithms else [algorithm]
    splits, n_splits = _make_splits(X, y, groups, "classification")

    results: dict[str, dict] = {}
    for candidate in candidates:
        fold_metrics: list[dict] = []
        oof_true: list = []
        oof_pred: list = []
        for train_idx, test_idx in splits:
            fold_model = clone(CLASSIFIERS[candidate])
            fold_model.fit(X[train_idx], y[train_idx])
            predictions = fold_model.predict(X[test_idx])
            if hasattr(fold_model, "predict_proba"):
                probabilities = fold_model.predict_proba(X[test_idx])[:, 1]
            else:
                probabilities = predictions
            fold_metrics.append(
                _classification_fold_metrics(
                    y[test_idx], predictions, probabilities
                )
            )
            oof_true.extend(y[test_idx].tolist())
            oof_pred.extend(predictions.tolist())
        mean, std = _aggregate_folds(fold_metrics)
        results[candidate] = {
            "mean": mean,
            "std": std,
            "folds": fold_metrics,
            "confusion_matrix": confusion_matrix(
                oof_true, oof_pred, labels=[0, 1]
            ).tolist(),
        }

    def _classification_key(name: str) -> tuple[float, float, float]:
        mean = results[name]["mean"]
        auc = mean.get("roc_auc")
        return (
            float(auc) if auc is not None else -1.0,
            mean.get("balanced_accuracy") or 0.0,
            mean.get("f1_score") or 0.0,
        )

    best_algorithm = max(candidates, key=_classification_key)
    best = results[best_algorithm]
    model = clone(CLASSIFIERS[best_algorithm]).fit(X, y)

    metrics = {
        "algorithm": best_algorithm,
        "selected_by": "mean_cv_roc_auc",
        "cv_folds": n_splits,
        "cv": results,
        "train_samples": len(y),
        "test_samples": sum(len(test_idx) for _, test_idx in splits),
        "confusion_matrix": best["confusion_matrix"],
    }
    for key, value in best["mean"].items():
        metrics[key] = value
        metrics[f"{key}_std"] = best["std"][key]
    return model, metrics


def train_regression(
    X: np.ndarray,
    y: np.ndarray,
    groups: np.ndarray | None = None,
    algorithm: str = "random_forest",
    compare_algorithms: bool = True,
) -> tuple[object, dict]:
    """Train a regression model and return (model, metrics_dict).

    Uses every fold of a group-aware cross-validation and, when
    ``compare_algorithms`` is True, selects the best regressor by mean CV R².
    """
    if algorithm not in REGRESSORS:
        raise ValueError(f"Unknown regression algorithm: {algorithm}")

    from sklearn.base import clone

    candidates = list(REGRESSORS) if compare_algorithms else [algorithm]
    splits, n_splits = _make_splits(X, y, groups, "regression")

    results: dict[str, dict] = {}
    for candidate in candidates:
        fold_metrics: list[dict] = []
        for train_idx, test_idx in splits:
            fold_model = clone(REGRESSORS[candidate])
            fold_model.fit(X[train_idx], y[train_idx])
            predictions = fold_model.predict(X[test_idx])
            fold_metrics.append(
                {
                    "mae": float(mean_absolute_error(y[test_idx], predictions)),
                    "rmse": float(
                        root_mean_squared_error(y[test_idx], predictions)
                    ),
                    "r2": (
                        float(r2_score(y[test_idx], predictions))
                        if len(np.unique(y[test_idx])) > 1
                        else 0.0
                    ),
                }
            )
        mean, std = _aggregate_folds(fold_metrics)
        results[candidate] = {"mean": mean, "std": std, "folds": fold_metrics}

    def _r2_key(name: str) -> float:
        value = results[name]["mean"].get("r2")
        return float(value) if value is not None else float("-inf")

    best_algorithm = max(candidates, key=_r2_key)
    best = results[best_algorithm]
    model = clone(REGRESSORS[best_algorithm]).fit(X, y)

    metrics = {
        "algorithm": best_algorithm,
        "selected_by": "mean_cv_r2",
        "cv_folds": n_splits,
        "cv": results,
        "train_samples": len(y),
        "test_samples": sum(len(test_idx) for _, test_idx in splits),
    }
    for key, value in best["mean"].items():
        metrics[key] = value
        metrics[f"{key}_std"] = best["std"][key]
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
    estimator = model
    # Unwrap a Pipeline (e.g. scaler + logistic regression).
    if hasattr(model, "named_steps"):
        estimator = model.named_steps.get("model", model)

    if hasattr(estimator, "feature_importances_"):
        importances = estimator.feature_importances_
    elif hasattr(estimator, "coef_"):
        importances = (
            np.abs(estimator.coef_[0])
            if estimator.coef_.ndim > 1
            else np.abs(estimator.coef_)
        )
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

# Bump this whenever the feature set or preprocessing changes in a way that
# invalidates previously trained artefacts. Bundles without the current
# version are never used for inference, which prevents legacy models trained
# with target leakage from serving predictions.
FEATURE_SCHEMA_VERSION = 2


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
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }
    joblib.dump(bundle, filepath)
    return filepath


def load_model(filepath: str) -> dict:
    """Load a saved model bundle from disk."""
    return joblib.load(filepath)
