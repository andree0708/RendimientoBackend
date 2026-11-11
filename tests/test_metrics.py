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

    def test_metrics_rejected_without_consent(self, client, auth_headers):
        sess = client.post("/api/v1/sessions", json={}, headers=auth_headers)
        session_id = sess.json()["id"]

        withdraw = client.post(
            "/api/v1/consent", json={"granted": False}, headers=auth_headers
        )
        assert withdraw.status_code == 200

        resp = client.post("/api/v1/metrics/batch", json={
            "session_id": session_id,
            "metrics": [
                {
                    "recorded_at": _now_str(),
                    "interval_seconds": 60,
                    "active_seconds": 30,
                    "idle_seconds": 30,
                }
            ],
        }, headers=auth_headers)
        assert resp.status_code == 403
        assert "consent" in resp.json()["detail"].lower()

        listed = client.get(f"/api/v1/metrics/session/{session_id}", headers=auth_headers)
        assert listed.json()["items"] == []

    def test_metrics_are_not_visible_to_other_users(self, client, auth_headers):
        sess = client.post("/api/v1/sessions", json={}, headers=auth_headers)
        session_id = sess.json()["id"]
        client.post("/api/v1/metrics/batch", json={
            "session_id": session_id,
            "metrics": [
                {
                    "recorded_at": _now_str(),
                    "interval_seconds": 60,
                    "active_seconds": 30,
                    "idle_seconds": 30,
                }
            ],
        }, headers=auth_headers)

        other = client.post("/api/v1/auth/register", json={
            "email": "metrics-other@example.com",
            "password": "otherpass123",
            "full_name": "Other User",
        }).json()
        other_headers = {"Authorization": f"Bearer {other['access_token']}"}

        resp = client.get(
            f"/api/v1/metrics/session/{session_id}", headers=other_headers
        )
        assert resp.status_code == 200
        assert resp.json()["items"] == []

    def test_pause_counters_are_per_interval_deltas(self, client, auth_headers):
        """The agent sends interval deltas; the backend accumulates them once."""
        sess = client.post("/api/v1/sessions", json={}, headers=auth_headers)
        session_id = sess.json()["id"]

        def send(pause_count: int, pause_total: int, active: int):
            resp = client.post("/api/v1/metrics/batch", json={
                "session_id": session_id,
                "metrics": [{
                    "recorded_at": _now_str(),
                    "interval_seconds": 60,
                    "active_seconds": active,
                    "idle_seconds": 60 - active,
                    "continuous_work_seconds": 120,
                    "pause_count": pause_count,
                    "pause_total_seconds": pause_total,
                }],
            }, headers=auth_headers)
            assert resp.status_code == 201

        send(pause_count=1, pause_total=30, active=50)
        send(pause_count=1, pause_total=60, active=40)

        session = client.get(
            f"/api/v1/sessions/{session_id}", headers=auth_headers
        ).json()
        assert session["total_active_seconds"] == 90
        assert session["pause_count"] == 2
        assert session["total_pause_seconds"] == 90

    def test_list_session_metrics(self, client, auth_headers):
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

    def test_activity_only_scope_redacts_app_tracking(self, client, auth_headers):
        client.post(
            "/api/v1/consent", json={"granted": True, "scope": "activity_only"},
            headers=auth_headers,
        )
        sess = client.post("/api/v1/sessions", json={}, headers=auth_headers)
        session_id = sess.json()["id"]

        resp = client.post("/api/v1/metrics/batch", json={
            "session_id": session_id,
            "metrics": [{
                "recorded_at": _now_str(),
                "interval_seconds": 60,
                "active_seconds": 50,
                "idle_seconds": 10,
                "app_switch_count": 5,
                "interruptions_count": 3,
                "app_category_seconds": 50,
                "tasks_started": 2,
                "tasks_completed": 1,
            }],
        }, headers=auth_headers)
        assert resp.status_code == 201
        stored = resp.json()[0]
        assert stored["active_seconds"] == 50
        assert stored["tasks_started"] == 2
        assert stored["app_switch_count"] == 0
        assert stored["interruptions_count"] == 0
        assert stored["app_category_seconds"] == 0

    def test_minimal_scope_keeps_only_timing(self, client, auth_headers):
        client.post(
            "/api/v1/consent", json={"granted": True, "scope": "minimal"},
            headers=auth_headers,
        )
        sess = client.post("/api/v1/sessions", json={}, headers=auth_headers)
        session_id = sess.json()["id"]

        resp = client.post("/api/v1/metrics/batch", json={
            "session_id": session_id,
            "metrics": [{
                "recorded_at": _now_str(),
                "interval_seconds": 60,
                "active_seconds": 50,
                "idle_seconds": 10,
                "continuous_work_seconds": 120,
                "pause_count": 1,
                "pause_total_seconds": 30,
                "app_switch_count": 4,
                "tasks_started": 2,
                "errors_reported": 1,
            }],
        }, headers=auth_headers)
        assert resp.status_code == 201
        stored = resp.json()[0]
        assert stored["active_seconds"] == 50
        assert stored["continuous_work_seconds"] == 120
        assert stored["pause_count"] == 0
        assert stored["app_switch_count"] == 0
        assert stored["tasks_started"] == 0
        assert stored["errors_reported"] == 0

    def test_invalid_scope_is_rejected(self, client, auth_headers):
        resp = client.post(
            "/api/v1/consent", json={"granted": True, "scope": "everything"},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    def test_batch_too_large_is_rejected(self, client, auth_headers):
        sess = client.post("/api/v1/sessions", json={}, headers=auth_headers)
        session_id = sess.json()["id"]
        resp = client.post("/api/v1/metrics/batch", json={
            "session_id": session_id,
            "metrics": [
                {"recorded_at": _now_str(), "interval_seconds": 60,
                 "active_seconds": 30, "idle_seconds": 30}
                for _ in range(501)
            ],
        }, headers=auth_headers)
        assert resp.status_code == 422

    def test_future_timestamp_is_rejected(self, client, auth_headers):
        from datetime import timedelta
        sess = client.post("/api/v1/sessions", json={}, headers=auth_headers)
        session_id = sess.json()["id"]
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        resp = client.post("/api/v1/metrics/batch", json={
            "session_id": session_id,
            "metrics": [{
                "recorded_at": future,
                "interval_seconds": 60,
                "active_seconds": 30,
                "idle_seconds": 30,
            }],
        }, headers=auth_headers)
        assert resp.status_code == 422

    def test_inconsistent_active_idle_is_rejected(self, client, auth_headers):
        sess = client.post("/api/v1/sessions", json={}, headers=auth_headers)
        session_id = sess.json()["id"]
        resp = client.post("/api/v1/metrics/batch", json={
            "session_id": session_id,
            "metrics": [{
                "recorded_at": _now_str(),
                "interval_seconds": 60,
                "active_seconds": 60,
                "idle_seconds": 60,
            }],
        }, headers=auth_headers)
        assert resp.status_code == 422

    def test_recent_metrics_span_sessions_newest_first(self, client, auth_headers):
        sess = client.post("/api/v1/sessions", json={}, headers=auth_headers)
        session_id = sess.json()["id"]
        client.post("/api/v1/metrics/batch", json={
            "session_id": session_id,
            "metrics": [{
                "recorded_at": _now_str(),
                "interval_seconds": 60,
                "active_seconds": 40,
                "idle_seconds": 20,
            }],
        }, headers=auth_headers)

        resp = client.get("/api/v1/metrics/recent", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["meta"]["total"] >= 1
        assert body["items"][0]["session_id"] == session_id

    def test_recent_metrics_are_not_visible_to_other_users(self, client, auth_headers):
        other = client.post("/api/v1/auth/register", json={
            "email": "recent-other@example.com",
            "password": "otherpass123",
            "full_name": "Other User",
        }).json()
        other_headers = {"Authorization": f"Bearer {other['access_token']}"}
        resp = client.get("/api/v1/metrics/recent", headers=other_headers)
        assert resp.status_code == 200
        assert resp.json()["items"] == []
