"""Tests for consent-gated self-reports, health and security headers."""


class TestSelfReportConsent:
    def test_self_report_requires_consent(self, client, auth_headers):
        client.post(
            "/api/v1/consent", json={"granted": False}, headers=auth_headers
        )
        resp = client.post("/api/v1/self-reports", json={
            "fatigue_level": 3,
            "stress_level": 2,
            "concentration_level": 4,
            "task_difficulty": 3,
            "perceived_effort": 3,
            "need_for_break": 2,
        }, headers=auth_headers)
        assert resp.status_code == 403

    def test_self_report_allowed_with_consent(self, client, auth_headers):
        resp = client.post("/api/v1/self-reports", json={
            "fatigue_level": 3,
            "stress_level": 2,
            "concentration_level": 4,
            "task_difficulty": 3,
            "perceived_effort": 3,
            "need_for_break": 2,
        }, headers=auth_headers)
        assert resp.status_code == 201


class TestHealth:
    def test_detailed_health_reports_db_and_models(self, client):
        resp = client.get("/health/detailed")
        assert resp.status_code == 200
        body = resp.json()
        assert body["database"]["ok"] is True
        assert body["models_dir"]["writable"] is True

    def test_security_headers_present(self, client):
        resp = client.get("/health")
        assert resp.headers["x-content-type-options"] == "nosniff"
        assert resp.headers["x-frame-options"] == "DENY"
        assert "content-security-policy" in resp.headers


class TestAuditCoverage:
    def test_train_is_audited(self, client, admin_headers):
        resp = client.post("/api/v1/ai/train", json={
            "model_type": "anomaly_detection",
            "use_demo_data": True,
        }, headers=admin_headers)
        assert resp.status_code == 200
        logs = client.get(
            "/api/v1/admin/audit-logs", headers=admin_headers
        ).json()
        train_logs = [e for e in logs if e["action"] == "ai.train"]
        assert len(train_logs) >= 1
        assert train_logs[0]["actor_email"] == "admin@worksense.ai"
