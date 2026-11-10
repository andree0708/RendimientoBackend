"""Tests for task endpoints."""

import pytest


class TestTasks:
    def test_create_task(self, client, auth_headers):
        resp = client.post("/api/v1/tasks", json={
            "title": "Test Task",
            "description": "Testing",
            "estimated_seconds": 1800,
            "complexity": 3,
        }, headers=auth_headers)
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "Test Task"
        assert data["status"] == "pending"
        assert data["complexity"] == 3
        return data

    def test_list_tasks(self, client, auth_headers):
        resp = client.get("/api/v1/tasks", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "meta" in data

    def test_complete_task(self, client, auth_headers):
        create = client.post("/api/v1/tasks", json={
            "title": "To complete",
            "estimated_seconds": 900,
            "complexity": 2,
        }, headers=auth_headers)
        task_id = create.json()["id"]

        update = client.patch(f"/api/v1/tasks/{task_id}", json={"status": "completed"},
                              headers=auth_headers)
        assert update.status_code == 200
        assert update.json()["status"] == "completed"

    def test_complete_task_after_starting_computes_actual_seconds(self, client, auth_headers):
        create = client.post("/api/v1/tasks", json={
            "title": "Started task",
            "estimated_seconds": 900,
            "complexity": 2,
        }, headers=auth_headers)
        task_id = create.json()["id"]

        started = client.patch(
            f"/api/v1/tasks/{task_id}", json={"status": "in_progress"},
            headers=auth_headers,
        )
        assert started.status_code == 200
        assert started.json()["started_at"] is not None

        completed = client.patch(
            f"/api/v1/tasks/{task_id}", json={"status": "completed"},
            headers=auth_headers,
        )
        assert completed.status_code == 200
        body = completed.json()
        assert body["status"] == "completed"
        assert body["completed_at"] is not None
        assert body["actual_seconds"] >= 0

    def test_add_task_result(self, client, auth_headers):
        create = client.post("/api/v1/tasks", json={
            "title": "Result task",
            "estimated_seconds": 1200,
            "complexity": 4,
        }, headers=auth_headers)
        task_id = create.json()["id"]

        result = client.post(f"/api/v1/tasks/{task_id}/results", json={
            "outcome": "completed",
            "errors_count": 0,
            "quality_rating": 5,
            "notes": "Done well",
        }, headers=auth_headers)
        assert result.status_code == 201
        assert result.json()["outcome"] == "completed"

    def test_task_not_found(self, client, auth_headers):
        resp = client.get("/api/v1/tasks/nonexistent", headers=auth_headers)
        assert resp.status_code == 404
