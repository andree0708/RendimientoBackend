"""Tests for activity metrics ingestion."""

from datetime import datetime, timezone
import pytest


def _now_str():
    return datetime.now(timezone.utc).isoformat()


class TestMetrics:
    def test_send_metrics_batch(self, client, auth_headers):
        # Start session first
        sess = client.post("/api/v1/sessions", json={}, headers=auth_headers)
        session_id = sess.json()["id"]

        metrics = [
            {
                "recorded_at": _now_str(),
                "interval_seconds": 60,
                "active_seconds": 45,
                "idle_seconds": 15,
                "continuous_work_seconds": 300,
                "pause_count": 1,
                "pause_total_seconds": 60,
                "app_switch_count": 3,
                "interruptions_count": 2,
                "tasks_started": 1,
                "tasks_completed": 0,
                "errors_reported": 0,
            }
        ]

        resp = client.post("/api/v1/metrics/batch", json={
            "session_id": session_id,
            "metrics": metrics,
        }, headers=auth_headers)
        assert resp.status_code == 201
        assert len(resp.json()) == 1

    def test_send_metrics_wrong_session(self, client, auth_headers):
        resp = client.post("/api/v1/metrics/batch", json={
            "session_id": "nonexistent-session",
            "metrics": [],
        }, headers=auth_headers)
        assert resp.status_code == 404

    def test_list_session_metrics(self, client, auth_headers):
        # Start session, send metrics, then list
        sess = client.post("/api/v1/sessions", json={}, headers=auth_headers)
        session_id = sess.json()["id"]

        client.post("/api/v1/metrics/batch", json={
            "session_id": session_id,
            "metrics": [
                {
                    "recorded_at": _now_str(),
                    "interval_seconds": 60,
                    "active_seconds": 50,
                    "idle_seconds": 10,
                    "continuous_work_seconds": 120,
                    "pause_count": 0,
                    "pause_total_seconds": 0,
                    "app_switch_count": 2,
                    "interruptions_count": 1,
                    "tasks_started": 0,
                    "tasks_completed": 0,
                    "errors_reported": 0,
                }
            ],
        }, headers=auth_headers)

        list_resp = client.get(f"/api/v1/metrics/session/{session_id}", headers=auth_headers)
        assert list_resp.status_code == 200
        data = list_resp.json()
        assert "items" in data
        assert len(data["items"]) >= 1
