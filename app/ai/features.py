"""Feature engineering for the ML pipeline.

Builds features from raw activity metrics:
- Continuous work duration
- Time since last pause
- Variation in task execution time
- Variation in operational errors
- Changes in pause frequency
- Activity variation between intervals
- Changes relative to the individual's causal historical average

Self-reports are used only to build labels. They are never model inputs,
because that would leak the target into the features.
"""

import numpy as np
import pandas as pd


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

# Self-report columns describe the outcome we want to predict (fatigue). They
# are labels, never predictors: using them as inputs makes the model copy the
# answer instead of learning from behaviour.
SELF_REPORT_COLUMNS = [
    "fatigue_level",
    "stress_level",
    "concentration_level",
    "perceived_effort",
    "need_for_break",
    "sleep_hours",
]

# The performance target is derived from task completion and error rates, so
# these columns (and aggregates computed from them) cannot be used as inputs.
PERFORMANCE_TARGET_DERIVED_COLUMNS = [
    "completion_rate",
    "error_rate",
    "total_tasks_completed",
    "total_errors",
    "error_std",
    "error_trend",
    "delta_completion_rate",
    "delta_error_rate",
]

IDENTIFIER_COLUMNS = ["user_id", "session_id"]
TARGET_COLUMNS = [
    "fatigue_label",
    "performance_variation",
    "next_fatigue_label",
    "next_performance_variation",
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

        # Basic aggregates.
        # Every metric row is one interval. Active/idle/pause/task/error
        # counters are per-interval deltas and are summed; continuous work is
        # a gauge (current streak duration) and its maximum is the session peak.
        total_active = g["active_seconds"].sum()
        total_idle = g["idle_seconds"].sum()
        total_continuous = g["continuous_work_seconds"].max()
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
                "session_start": g["recorded_at"].min(),
                "session_end": g["recorded_at"].max(),
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


def engineer_report_features(
    metrics_df: pd.DataFrame, reports_df: pd.DataFrame
) -> pd.DataFrame:
    """Build one feature row per self-report using only prior activity.

    A self-report can be submitted in the middle of a session. Aggregating the
    whole session would use activity that happened *after* the report, which is
    look-ahead leakage. This function truncates each session at ``reported_at``.
    """
    if metrics_df.empty or reports_df.empty:
        return pd.DataFrame()
    if "session_id" not in reports_df.columns or "reported_at" not in reports_df.columns:
        return pd.DataFrame()

    metrics = metrics_df.copy()
    metrics["recorded_at"] = pd.to_datetime(
        metrics["recorded_at"], utc=True
    ).dt.tz_localize(None)
    reports = reports_df.dropna(subset=["session_id"]).copy()
    reports["reported_at"] = pd.to_datetime(
        reports["reported_at"], utc=True
    ).dt.tz_localize(None)

    rows: list[dict] = []
    for _, report in reports.iterrows():
        window = metrics[
            (metrics["user_id"] == report["user_id"])
            & (metrics["session_id"] == report["session_id"])
            & (metrics["recorded_at"] <= report["reported_at"])
        ]
        if window.empty:
            continue
        engineered = engineer_session_features(window)
        if engineered.empty:
            continue
        row = engineered.iloc[0].to_dict()
        # Order reports chronologically for the causal baseline.
        row["session_start"] = report["reported_at"]
        row["reported_at"] = report["reported_at"]
        row["fatigue_level"] = report["fatigue_level"]
        row["fatigue_label"] = int(report["fatigue_level"] >= 3)
        rows.append(row)
    return pd.DataFrame(rows)


def add_individual_baseline(
    features_df: pd.DataFrame,
    historical_df: pd.DataFrame | None = None,
    causal: bool = False,
) -> pd.DataFrame:
    """Add columns comparing each session to the user's historical average.

    If ``historical_df`` is provided, baselines are computed from it.
    With ``causal=True`` only *previous* sessions are used, which is required
    when the target is a future window (otherwise the baseline would contain
    look-ahead information). Otherwise a leave-one-out mean is used.
    Users with a single session get a delta of 0: there is no history yet.
    """
    df = features_df.copy()
    baseline_cols = [
        "total_active_seconds",
        "total_continuous_work",
        "total_pause_count",
        "completion_rate",
        "error_rate",
        "work_ratio",
    ]
    baseline_cols = [col for col in baseline_cols if col in df.columns]
    if not baseline_cols or df.empty:
        return df

    if historical_df is not None and not historical_df.empty:
        available = [col for col in baseline_cols if col in historical_df.columns]
        if available:
            user_baselines = historical_df.groupby("user_id")[available].mean()
            for col in available:
                df[f"delta_{col}"] = df[col] - df["user_id"].map(user_baselines[col])
        return df

    if causal:
        if "session_start" in df.columns:
            df = df.sort_values(["user_id", "session_start"]).reset_index(drop=True)
        for col in baseline_cols:
            prior_mean = df.groupby("user_id")[col].transform(
                lambda series: series.shift(1).expanding().mean()
            )
            df[f"delta_{col}"] = (df[col] - prior_mean).fillna(0.0)
        return df

    grouped = df.groupby("user_id")[baseline_cols]
    sums = grouped.transform("sum")
    counts = grouped.transform("count")
    leave_one_out = (sums - df[baseline_cols]) / (counts - 1).replace(0, np.nan)
    for col in baseline_cols:
        df[f"delta_{col}"] = (df[col] - leave_one_out[col]).fillna(0.0)
    return df


def add_next_session_target(
    features_df: pd.DataFrame, target_col: str, output_col: str
) -> pd.DataFrame:
    """Add the next session's target value for the same user.

    This turns a contemporaneous label into a genuine forecast target. The
    last session per user has no future value and is dropped by the caller.
    """
    if "session_start" in features_df.columns:
        df = features_df.sort_values(
            ["user_id", "session_start"]
        ).reset_index(drop=True)
    else:
        df = features_df.copy()
    df[output_col] = df.groupby("user_id")[target_col].shift(-1)
    return df


def select_model_features(features_df: pd.DataFrame, model_type: str) -> pd.DataFrame:
    """Return only the columns that are valid model inputs for ``model_type``.

    Keeping the allow/deny logic in one place prevents target leakage from
    creeping back in when new engineered columns are added.
    """
    excluded = set(IDENTIFIER_COLUMNS) | set(TARGET_COLUMNS) | set(SELF_REPORT_COLUMNS)
    if model_type == "performance_regression":
        excluded |= set(PERFORMANCE_TARGET_DERIVED_COLUMNS)

    columns = [
        column
        for column in features_df.columns
        if column not in excluded
        and pd.api.types.is_numeric_dtype(features_df[column])
    ]
    if not columns:
        raise ValueError(f"No valid feature columns for model type {model_type!r}")
    return features_df[columns].astype(float).fillna(0.0)


def align_feature_matrix(
    features_df: pd.DataFrame, feature_names: list[str]
) -> np.ndarray:
    """Return X with exactly ``feature_names`` in the order used at training.

    Missing columns are filled with 0 so inference always matches training,
    even when a feature cannot be computed for the current window.
    """
    if features_df.empty:
        return np.zeros((1, len(feature_names)))
    aligned = features_df.reindex(columns=feature_names)
    return aligned.astype(float).fillna(0.0).values


def link_reports_to_sessions(
    reports_df: pd.DataFrame, metrics_df: pd.DataFrame
) -> pd.DataFrame:
    """Fill missing ``session_id`` values using session time windows.

    Older clients did not send ``session_id`` when submitting a self-report.
    Dropping those rows silently removed every real label from training, so we
    assign each report to the most recent session that had activity before it.
    """
    if reports_df.empty or metrics_df.empty:
        return reports_df
    if "session_id" not in reports_df.columns or "reported_at" not in reports_df.columns:
        return reports_df

    df = reports_df.copy()
    missing = df["session_id"].isna()
    if not missing.any():
        return df

    windows = (
        metrics_df.groupby(["user_id", "session_id"])["recorded_at"]
        .agg(session_start="min", session_end="max")
        .reset_index()
    )
    # Normalise to naive UTC so SQLite (naive) and Postgres (aware) agree.
    df["reported_at"] = pd.to_datetime(df["reported_at"], utc=True).dt.tz_localize(None)
    windows["session_start"] = pd.to_datetime(
        windows["session_start"], utc=True
    ).dt.tz_localize(None)
    windows["session_end"] = pd.to_datetime(
        windows["session_end"], utc=True
    ).dt.tz_localize(None)

    for idx, report in df[missing].iterrows():
        candidates = windows[
            (windows["user_id"] == report["user_id"])
            & (windows["session_start"] <= report["reported_at"])
        ]
        if candidates.empty:
            continue
        best = candidates.sort_values("session_end").iloc[-1]
        df.at[idx, "session_id"] = best["session_id"]
    return df


def get_feature_matrix(features_df: pd.DataFrame) -> tuple[np.ndarray, list[str]]:
    """Return (X, feature_names) filling NaN with 0 and ready for model input."""
    numeric = features_df.select_dtypes(include=[np.number]).copy()
    numeric = numeric.fillna(0)
    feature_names = numeric.columns.tolist()
    return numeric.values, feature_names
