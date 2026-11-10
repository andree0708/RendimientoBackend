"""Tests for the local metric collector's interval semantics."""

from agent import collector as collector_module
from agent.collector import MetricCollector


def _collector(monkeypatch) -> MetricCollector:
    monkeypatch.setattr(collector_module, "_get_idle_seconds", lambda: 0)
    monkeypatch.setattr(
        collector_module, "_get_foreground_app_category", lambda: "development"
    )
    return MetricCollector(idle_threshold=300)


def test_cumulative_counters_are_emitted_as_interval_deltas(monkeypatch):
    collector = _collector(monkeypatch)

    collector.record_task_started()
    collector.record_error()
    first = collector.collect(60)

    assert first["tasks_started"] == 1
    assert first["tasks_completed"] == 0
    assert first["errors_reported"] == 1

    # No new events: the next interval must report zeros, not the cumulative
    # totals again.
    second = collector.collect(60)
    assert second["tasks_started"] == 0
    assert second["tasks_completed"] == 0
    assert second["errors_reported"] == 0

    collector.record_task_started()
    collector.record_task_completed()
    third = collector.collect(60)
    assert third["tasks_started"] == 1
    assert third["tasks_completed"] == 1


def test_app_category_seconds_is_a_per_interval_delta(monkeypatch):
    collector = _collector(monkeypatch)

    first = collector.collect(60)
    second = collector.collect(60)

    assert first["app_category_seconds"] == 60
    assert second["app_category_seconds"] == 60


def test_pause_count_is_emitted_once(monkeypatch):
    collector = _collector(monkeypatch)

    # Active interval: no pause.
    assert collector.collect(60)["pause_count"] == 0

    # Idle transition: one new pause.
    monkeypatch.setattr(collector_module, "_get_idle_seconds", lambda: 1000)
    assert collector.collect(60)["pause_count"] == 1

    # Still idle: no additional pause event.
    assert collector.collect(60)["pause_count"] == 0
