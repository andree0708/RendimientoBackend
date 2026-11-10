"""Synthetic data generator for training and demonstration.

IMPORTANT: All data produced here is synthetic and clearly labeled as DEMO.
It is used only when real data is insufficient for training.
Results from synthetic data must NOT be presented as scientific evidence.
"""

import json
import random
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd


def generate_demo_dataset(
    n_users: int = 10,
    sessions_per_user: int = 15,
    metrics_per_session: int = 20,
    seed: int = 42,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Generate a realistic synthetic dataset of activity metrics + self-reports.

    Returns:
        (metrics_df, reports_df) — both DataFrames clearly tagged with
        ``is_demo = True``.
    """
    rng = np.random.default_rng(seed)
    random.seed(seed)

    metrics_rows: list[dict] = []
    report_rows: list[dict] = []

    for user_idx in range(n_users):
        user_id = f"demo_user_{user_idx:03d}"
        # Each user has a personal baseline so comparisons are individual
        base_activity = rng.uniform(180, 300)  # seconds active per interval
        base_idle = rng.uniform(20, 60)
        base_pause_freq = rng.uniform(0.05, 0.2)
        base_error_rate = rng.uniform(0.02, 0.1)
        base_fatigue = rng.integers(2, 4)  # self-reported fatigue baseline

        session_date = datetime(2025, 1, 1, tzinfo=timezone.utc)

        for s_idx in range(sessions_per_user):
            session_id = f"demo_sess_{user_idx:03d}_{s_idx:03d}"
            started_at = session_date + timedelta(days=int(s_idx), hours=int(rng.integers(7, 11)))

            # Simulate fatigue buildup within a session
            cumulative_work = 0
            for m_idx in range(metrics_per_session):
                recorded_at = started_at + timedelta(minutes=int(m_idx))

                # Fatigue factor grows with continuous work within the session
                fatigue_factor = cumulative_work / 7200  # normalise by 2h
                fatigue_factor = min(fatigue_factor, 1.5)

                active_seconds = max(0, int(base_activity * (1 - 0.15 * float(fatigue_factor)) + rng.normal(0, 20)))
                idle_seconds = max(0, int(base_idle * (1 + 0.4 * float(fatigue_factor)) + rng.normal(0, 10)))
                continuous_work_seconds = active_seconds + max(0, int(60 * (1 + float(fatigue_factor))))
                pause_count = max(0, int(rng.poisson(base_pause_freq * (1 + float(fatigue_factor) * 2))))
                app_switch_count = max(0, int(rng.poisson(2 + float(fatigue_factor) * 3)))
                interruptions_count = max(0, int(rng.poisson(1 + float(fatigue_factor) * 2)))
                tasks_completed = max(0, int(rng.poisson(0.8 * (1 - 0.2 * float(fatigue_factor)))))
                tasks_started = tasks_completed + max(0, int(rng.poisson(0.3)))
                errors_reported = max(0, int(rng.poisson(base_error_rate * (1 + float(fatigue_factor) * 3))))

                metrics_rows.append(
                    {
                        "user_id": user_id,
                        "session_id": session_id,
                        "recorded_at": recorded_at,
                        "interval_index": int(m_idx),
                        "active_seconds": int(active_seconds),
                        "idle_seconds": int(idle_seconds),
                        "continuous_work_seconds": int(continuous_work_seconds),
                        "pause_count": int(pause_count),
                        "pause_total_seconds": int(pause_count) * int(rng.integers(30, 120)),
                        "app_switch_count": int(app_switch_count),
                        "interruptions_count": int(interruptions_count),
                        "tasks_started": int(tasks_started),
                        "tasks_completed": int(tasks_completed),
                        "errors_reported": int(errors_reported),
                        "is_demo": True,
                    }
                )
                cumulative_work += active_seconds

            # Self-report for this session (mid-session or end)
            fatigue_level = min(5, max(1, int(base_fatigue) + int(rng.integers(-1, 3)) + int(s_idx * 0.1)))
            fatigue_level = min(int(fatigue_level), 10)
            stress_level = min(10, max(1, fatigue_level + int(rng.integers(-1, 2))))
            concentration_level = min(10, max(1, 11 - fatigue_level + int(rng.integers(-1, 2))))
            task_difficulty = int(rng.integers(2, 6))
            perceived_effort = min(10, max(1, task_difficulty + fatigue_level // 2))
            need_for_break = min(10, max(1, fatigue_level + int(rng.integers(0, 2))))
            sleep_hours = round(rng.uniform(4, 9), 1)
            sleep_quality = int(rng.integers(1, 6))

            report_rows.append(
                {
                    "user_id": user_id,
                    "session_id": session_id,
                    "reported_at": started_at + timedelta(minutes=15),
                    "fatigue_level": fatigue_level,
                    "stress_level": stress_level,
                    "concentration_level": concentration_level,
                    "task_difficulty": task_difficulty,
                    "perceived_effort": perceived_effort,
                    "need_for_break": need_for_break,
                    "sleep_hours": sleep_hours,
                    "sleep_quality": sleep_quality,
                    "rest_quality_previous_night": int(rng.integers(1, 6)),
                    "is_demo": True,
                }
            )

    metrics_df = pd.DataFrame(metrics_rows)
    reports_df = pd.DataFrame(report_rows)
    return metrics_df, reports_df


def build_labels_fatigue(reports_df: pd.DataFrame, threshold: int = 3) -> pd.Series:
    """Build binary fatigue labels from self-reports.

    Label = 1 when fatigue_level >= threshold (signals of fatigue).
    """
    return (reports_df["fatigue_level"] >= threshold).astype(int)


def build_labels_performance(metrics_df: pd.DataFrame) -> pd.Series:
    """Build a performance-variation label from task metrics.

    Positive variation = better-than-baseline performance.
    Negative variation = performance decrease (target for prediction).
    Computed as: completion_rate - error_rate, normalised.
    """
    # Group by session and compute aggregate performance signal
    grouped = metrics_df.groupby("session_id").agg(
        total_completed=("tasks_completed", "sum"),
        total_started=("tasks_started", "sum"),
        total_errors=("errors_reported", "sum"),
    )
    grouped["completion_rate"] = grouped["total_completed"] / grouped["total_started"].clip(lower=1)
    grouped["error_rate"] = grouped["total_errors"] / grouped["total_completed"].clip(lower=1)
    # Variation: positive means good performance, negative means decline
    grouped["performance_variation"] = grouped["completion_rate"] - grouped["error_rate"] * 0.5 - 0.5

    # Merge back to metrics df
    metrics_df = metrics_df.merge(
        grouped[["performance_variation"]].reset_index(), on="session_id", how="left"
    )
    return metrics_df["performance_variation"]
