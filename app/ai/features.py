"""Feature engineering for the ML pipeline.

Builds features from raw activity metrics and self-reports:
- Continuous work duration
- Time since last pause
- Variation in task execution time
- Variation in operational errors
- Changes in pause frequency
- Activity variation between intervals
- Changes relative to the individual's historical average
- Evolution of self-reported fatigue
"""

import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler


FEATURE_COLUMNS = [
    "active_seconds",
    "idle_seconds",
    "continuous_work_seconds",
    "pause_count",
    "pause_total_seconds",
    "app_switch_count",
    "interruptions_count",
    "tasks_started",
    "tasks_completed",
    "errors_reported",
]


def engineer_session_features(metrics_df: pd.DataFrame) -> pd.DataFrame:
    """Build aggregate features per session from raw interval metrics.

    Returns a DataFrame with one row per (user_id, session_id) containing
    engineered features suitable for training and inference.
    """
    df = metrics_df.copy()

    # Sort by user, session, and time
    df = df.sort_values(["user_id", "session_id", "recorded_at"])

    features: list[dict] = []

    for (user_id, session_id), group in df.groupby(["user_id", "session_id"]):
        g = group.reset_index(drop=True)

        # Basic aggregates
        total_active = g["active_seconds"].sum()
        total_idle = g["idle_seconds"].sum()
        total_continuous = g["continuous_work_seconds"].sum()
        total_pause_count = g["pause_count"].sum()
        total_pause_time = g["pause_total_seconds"].sum()
        total_app_switches = g["app_switch_count"].sum()
        total_interruptions = g["interruptions_count"].sum()
        total_tasks_started = g["tasks_started"].sum()
        total_tasks_completed = g["tasks_completed"].sum()
        total_errors = g["errors_reported"].sum()

        # Derived features
        completion_rate = total_tasks_completed / max(total_tasks_started, 1)
        error_rate = total_errors / max(total_tasks_completed, 1)
        work_ratio = total_active / max(total_active + total_idle, 1)
        avg_pause_duration = total_pause_time / max(total_pause_count, 1)

        # Variation measures (standard deviation across intervals)
        active_std = g["active_seconds"].std() or 0
        idle_std = g["idle_seconds"].std() or 0
        error_std = g["errors_reported"].std() or 0

        # Trend features (last interval vs first)
        if len(g) > 1:
            active_trend = g["active_seconds"].iloc[-1] - g["active_seconds"].iloc[0]
            idle_trend = g["idle_seconds"].iloc[-1] - g["idle_seconds"].iloc[0]
            error_trend = g["errors_reported"].iloc[-1] - g["errors_reported"].iloc[0]
        else:
            active_trend = 0
            idle_trend = 0
            error_trend = 0

        # Continuous work at the end of the session (fatigue indicator)
        last_continuous = g["continuous_work_seconds"].iloc[-1] if len(g) > 0 else 0

        features.append(
            {
                "user_id": user_id,
                "session_id": session_id,
                "total_active_seconds": total_active,
                "total_idle_seconds": total_idle,
                "total_continuous_work": total_continuous,
                "total_pause_count": total_pause_count,
                "total_pause_time": total_pause_time,
                "total_app_switches": total_app_switches,
                "total_interruptions": total_interruptions,
                "completion_rate": completion_rate,
                "error_rate": error_rate,
                "work_ratio": work_ratio,
                "avg_pause_duration": avg_pause_duration,
                "active_std": active_std,
                "idle_std": idle_std,
                "error_std": error_std,
                "active_trend": active_trend,
                "idle_trend": idle_trend,
                "error_trend": error_trend,
                "last_continuous_work": last_continuous,
                "total_tasks_completed": total_tasks_completed,
                "total_errors": total_errors,
                "interval_count": len(g),
            }
        )

    return pd.DataFrame(features)


def add_individual_baseline(
    features_df: pd.DataFrame, historical_df: pd.DataFrame | None = None
) -> pd.DataFrame:
    """Add columns comparing each session to the user's historical average.

    If ``historical_df`` is provided, baselines are computed from it;
    otherwise baselines are computed from ``features_df`` itself (in-sample).
    """
    baseline_source = historical_df if historical_df is not None else features_df

    baseline_cols = [
        "total_active_seconds",
        "total_continuous_work",
        "total_pause_count",
        "completion_rate",
        "error_rate",
        "work_ratio",
    ]

    user_baselines = baseline_source.groupby("user_id")[baseline_cols].mean()

    def _add_deltas(row):
        uid = row["user_id"]
        if uid in user_baselines.index:
            baseline = user_baselines.loc[uid]
            for col in baseline_cols:
                if col in baseline.index:
                    row[f"delta_{col}"] = row[col] - baseline[col]
        return row

    return features_df.apply(_add_deltas, axis=1)


def merge_self_reports(features_df: pd.DataFrame, reports_df: pd.DataFrame) -> pd.DataFrame:
    """Merge self-report indicators into session-level features."""
    report_agg = reports_df.groupby(["user_id", "session_id"]).agg(
        fatigue_level=("fatigue_level", "mean"),
        stress_level=("stress_level", "mean"),
        concentration_level=("concentration_level", "mean"),
        perceived_effort=("perceived_effort", "mean"),
        need_for_break=("need_for_break", "mean"),
        sleep_hours=("sleep_hours", "mean"),
    ).reset_index()

    return features_df.merge(report_agg, on=["user_id", "session_id"], how="left")


def get_feature_matrix(features_df: pd.DataFrame) -> tuple[np.ndarray, list[str]]:
    """Return (X, feature_names) filling NaN with 0 and ready for model input."""
    numeric = features_df.select_dtypes(include=[np.number]).copy()
    numeric = numeric.fillna(0)
    feature_names = numeric.columns.tolist()
    return numeric.values, feature_names


def fit_scaler(X: np.ndarray) -> StandardScaler:
    """Fit a StandardScaler on the feature matrix."""
    scaler = StandardScaler()
    scaler.fit(X)
    return scaler
