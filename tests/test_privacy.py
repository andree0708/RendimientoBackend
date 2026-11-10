"""Tests for consent, profile update, export, and data deletion."""

import pytest


class TestConsent:
    def test_get_consent_returns_current_status(self, client, auth_headers):
        resp = client.get("/api/v1/consent", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["granted"] is True

    def test_withdraw_and_regrant_consent(self, client, auth_headers):
        withdraw = client.post(
            "/api/v1/consent", json={"granted": False}, headers=auth_headers
        )
        assert withdraw.status_code == 200
        assert withdraw.json()["granted"] is False
        assert withdraw.json()["withdrawn_at"] is not None

        status = client.get("/api/v1/consent", headers=auth_headers)
        assert status.json()["granted"] is False

        grant = client.post(
            "/api/v1/consent", json={"granted": True, "scope": "activity_only"},
            headers=auth_headers,
        )
        assert grant.status_code == 200
        assert grant.json()["granted"] is True
        assert grant.json()["scope"] == "activity_only"


class TestProfile:
    def test_update_profile(self, client, auth_headers):
        resp = client.patch(
            "/api/v1/users/me", json={"full_name": "Updated Name"}, headers=auth_headers
        )
        assert resp.status_code == 200
        assert resp.json()["full_name"] == "Updated Name"

    def test_update_profile_ignores_email(self, client, auth_headers):
        resp = client.patch(
            "/api/v1/users/me",
            json={"full_name": "Name", "email": "attacker@example.com"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["email"] == "testuser@worksense.ai"


class TestPrivacy:
    def _create_data(self, client, auth_headers):
        session = client.post(
            "/api/v1/sessions", json={"notes": "privacy test"}, headers=auth_headers
        )
        assert session.status_code == 201
        session_id = session.json()["id"]

        task = client.post(
            "/api/v1/tasks",
            json={"title": "Private task", "session_id": session_id},
            headers=auth_headers,
        )
        assert task.status_code == 201
        return session_id

    def test_export_contains_user_data(self, client, auth_headers):
        session_id = self._create_data(client, auth_headers)

        resp = client.get("/api/v1/privacy/export", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["user"]["email"] == "testuser@worksense.ai"
        assert "hashed_password" not in data["user"]
        assert len(data["sessions"]) == 1
        assert data["sessions"][0]["id"] == session_id
        assert len(data["tasks"]) == 1
        assert len(data["consent_records"]) >= 1

    def test_delete_removes_collected_data(self, client, auth_headers):
        self._create_data(client, auth_headers)

        resp = client.delete("/api/v1/privacy/data", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["account_retained"] is True
        assert body["deleted"]["sessions"] == 1
        assert body["deleted"]["tasks"] == 1

        export = client.get("/api/v1/privacy/export", headers=auth_headers).json()
        assert export["sessions"] == []
        assert export["tasks"] == []
        assert export["activity_metrics"] == []
        assert export["self_reports"] == []
        assert export["consent_records"][-1]["granted"] is False

    def test_export_requires_auth(self, client):
        resp = client.get("/api/v1/privacy/export")
        assert resp.status_code == 401

    def test_export_is_audited(self, client, auth_headers, admin_headers):
        self._create_data(client, auth_headers)

        assert client.get("/api/v1/privacy/export", headers=auth_headers).status_code == 200

        logs = client.get(
            "/api/v1/admin/audit-logs", headers=admin_headers
        ).json()
        export_logs = [entry for entry in logs if entry["action"] == "privacy.export"]
        assert len(export_logs) == 1
        assert export_logs[0]["actor_email"] == "testuser@worksense.ai"
        assert "sessions=1" in export_logs[0]["detail"]

    def test_delete_is_audited(self, client, auth_headers, admin_headers):
        self._create_data(client, auth_headers)

        assert client.delete("/api/v1/privacy/data", headers=auth_headers).status_code == 200

        logs = client.get(
            "/api/v1/admin/audit-logs", headers=admin_headers
        ).json()
        delete_logs = [entry for entry in logs if entry["action"] == "privacy.delete"]
        assert len(delete_logs) == 1
        assert delete_logs[0]["actor_email"] == "testuser@worksense.ai"
        assert "sessions=1" in delete_logs[0]["detail"]
        assert "consent_withdrawn=True" in delete_logs[0]["detail"]

    def test_consent_change_is_audited(self, client, auth_headers, admin_headers):
        client.post(
            "/api/v1/consent", json={"granted": False}, headers=auth_headers
        )

        logs = client.get(
            "/api/v1/admin/audit-logs", headers=admin_headers
        ).json()
        consent_logs = [
            entry for entry in logs if entry["action"] == "consent.updated"
        ]
        assert len(consent_logs) == 1
        assert "granted=False" in consent_logs[0]["detail"]
