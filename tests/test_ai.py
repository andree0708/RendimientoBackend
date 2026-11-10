"""Tests for AI model endpoints."""

import pytest


class TestAI:
    def test_list_models(self, client, admin_headers):
        resp = client.get("/api/v1/ai/models", headers=admin_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_list_models_requires_admin(self, client, auth_headers):
        """Regular users must not see internal model paths or metrics."""
        resp = client.get("/api/v1/ai/models", headers=auth_headers)
        assert resp.status_code == 403

    def test_train_model_requires_admin(self, client, auth_headers):
        """Regular user cannot train models."""
        resp = client.post("/api/v1/ai/train", json={
            "model_type": "fatigue_classification",
            "use_demo_data": True,
        }, headers=auth_headers)
        assert resp.status_code == 403

    def test_train_model_as_admin(self, client, admin_headers):
        resp = client.post("/api/v1/ai/train", json={
            "model_type": "fatigue_classification",
            "use_demo_data": True,
        }, headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "model_version_id" in data
        assert data["metrics"] is not None

        # A demo-trained model is registered for audit but never activated.
        models = client.get("/api/v1/ai/models", headers=admin_headers).json()
        trained = next(m for m in models if m["id"] == data["model_version_id"])
        assert trained["is_active"] is False
        assert "DEMO data: True" in trained["notes"]

    def test_train_performance_model(self, client, admin_headers):
        resp = client.post("/api/v1/ai/train", json={
            "model_type": "performance_regression",
            "use_demo_data": True,
        }, headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_train_anomaly_model(self, client, admin_headers):
        resp = client.post("/api/v1/ai/train", json={
            "model_type": "anomaly_detection",
            "use_demo_data": True,
        }, headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

        models = client.get("/api/v1/ai/models", headers=admin_headers).json()
        trained = next(m for m in models if m["id"] == data["model_version_id"])
        assert trained["is_active"] is False

    def test_assess_fatigue(self, client, auth_headers):
        resp = client.post("/api/v1/ai/predict/fatigue", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "risk_category" in data
        assert "risk_probability" in data
        assert data["risk_category"] in ("low", "moderate", "high", "unknown")

    def test_predict_performance(self, client, auth_headers):
        resp = client.post("/api/v1/ai/predict/performance", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "risk_label" in data
        assert "predicted_variation" in data
        assert "horizon_minutes" in data

    def test_fatigue_history(self, client, auth_headers):
        resp = client.get("/api/v1/ai/fatigue/history", headers=auth_headers)
        assert resp.status_code == 200
        assert "items" in resp.json()

    def test_performance_history(self, client, auth_headers):
        resp = client.get("/api/v1/ai/performance/history", headers=auth_headers)
        assert resp.status_code == 200
        assert "items" in resp.json()
