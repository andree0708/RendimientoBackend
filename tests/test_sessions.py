"""Tests for work session endpoints."""

import pytest


class TestSessions:
    def test_start_session(self, client, auth_headers):
        resp = client.post("/api/v1/sessions", json={"notes": "Test session"},
                           headers=auth_headers)
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "active"
        assert "started_at" in data
        return data

    def test_start_duplicate_session_fails(self, client, auth_headers):
        # Start first session
        resp1 = client.post("/api/v1/sessions", json={}, headers=auth_headers)
        assert resp1.status_code == 201

        # Try to start another
        resp2 = client.post("/api/v1/sessions", json={}, headers=auth_headers)
        assert resp2.status_code == 409

    def test_stop_session(self, client, auth_headers):
        start = client.post("/api/v1/sessions", json={}, headers=auth_headers)
        assert start.status_code == 201
        session_id = start.json()["id"]

        stop = client.post(f"/api/v1/sessions/{session_id}/stop", headers=auth_headers)
        assert stop.status_code == 200
        assert stop.json()["status"] == "completed"

    def test_list_sessions(self, client, auth_headers):
        resp = client.get("/api/v1/sessions", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "meta" in data

    def test_get_active_session_none(self, client, auth_headers):
        resp = client.get("/api/v1/sessions/active/current", headers=auth_headers)
        # Returns null or 200 with session
        assert resp.status_code in (200, 404)

    def test_sessions_require_auth(self, client):
        resp = client.get("/api/v1/sessions")
        assert resp.status_code == 401
