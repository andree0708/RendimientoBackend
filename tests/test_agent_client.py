"""Tests for the local agent's API client and consent handling."""

import pytest
import requests

from agent import config as config_module
from agent.api_client import AgentAPIClient
from agent.config import AgentConfig


@pytest.fixture(autouse=True)
def _isolate_agent_home(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(
        config_module, "CONFIG_FILE", tmp_path / "agent_config.json"
    )


class FakeResponse:
    def __init__(self, status_code: int, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = str(self._payload)

    def json(self):
        return self._payload


def make_client() -> AgentAPIClient:
    return AgentAPIClient(
        AgentConfig(
            backend_url="http://backend.test",
            email="agent@example.com",
            password="secret",
        )
    )


def test_consent_status_is_read_from_backend(monkeypatch):
    client = make_client()
    monkeypatch.setattr(
        "agent.api_client.requests.get",
        lambda *a, **k: FakeResponse(200, {"granted": False}),
    )

    assert client.get_consent() is False


def test_consent_revocation_stops_ingestion_without_buffering(monkeypatch):
    client = make_client()
    client.session_id = "session-1"
    monkeypatch.setattr(
        "agent.api_client.requests.post",
        lambda *a, **k: FakeResponse(403, {"detail": "consent required"}),
    )

    assert client.send_metrics([{"active_seconds": 10}]) is False
    assert client.consent_revoked is True
    assert len(client._buffer) == 0


def test_network_error_buffers_metrics_with_their_session(monkeypatch):
    client = make_client()
    client.session_id = "session-old"

    def raise_error(*args, **kwargs):
        raise requests.RequestException("offline")

    monkeypatch.setattr("agent.api_client.requests.post", raise_error)
    client.send_metrics([{"active_seconds": 5}])

    assert len(client._buffer) == 1
    assert client._buffer[0]["session_id"] == "session-old"

    captured = {}

    def successful_post(url, json=None, headers=None, timeout=None):
        captured["json"] = json
        return FakeResponse(201, [])

    monkeypatch.setattr("agent.api_client.requests.post", successful_post)
    client.session_id = "session-new"
    client._flush_buffer()

    # Buffered data must stay attached to the session where it was collected.
    assert captured["json"]["session_id"] == "session-old"
    assert len(client._buffer) == 0


def test_start_session_reuses_existing_session_on_conflict(monkeypatch):
    client = make_client()
    monkeypatch.setattr(
        "agent.api_client.requests.post",
        lambda *a, **k: FakeResponse(409, {"detail": "already active"}),
    )
    monkeypatch.setattr(
        "agent.api_client.requests.get",
        lambda *a, **k: FakeResponse(200, {"id": "existing-session"}),
    )

    assert client.start_session() == "existing-session"
    assert client.session_id == "existing-session"


def test_stop_session_resolves_active_session(monkeypatch):
    client = make_client()
    calls = []

    monkeypatch.setattr(
        "agent.api_client.requests.get",
        lambda *a, **k: FakeResponse(200, {"id": "active-1"}),
    )

    def fake_post(url, **kwargs):
        calls.append(url)
        return FakeResponse(200, {"id": "active-1", "status": "completed"})

    monkeypatch.setattr("agent.api_client.requests.post", fake_post)

    assert client.stop_session() is True
    assert any("active-1/stop" in url for url in calls)
    assert client.session_id is None


def test_self_report_is_linked_to_active_session(monkeypatch):
    client = make_client()
    captured = {}

    monkeypatch.setattr(
        "agent.api_client.requests.get",
        lambda *a, **k: FakeResponse(200, {"id": "session-report"}),
    )

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["json"] = json
        return FakeResponse(201, {"id": "report-1"})

    monkeypatch.setattr("agent.api_client.requests.post", fake_post)

    assert client.submit_self_report({"fatigue_level": 3}) is True
    assert captured["json"]["session_id"] == "session-report"


def test_self_report_without_active_session_is_still_submitted(monkeypatch):
    client = make_client()
    captured = {}

    monkeypatch.setattr(
        "agent.api_client.requests.get",
        lambda *a, **k: FakeResponse(200, None),
    )

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["json"] = json
        return FakeResponse(201, {"id": "report-2"})

    monkeypatch.setattr("agent.api_client.requests.post", fake_post)

    assert client.submit_self_report({"fatigue_level": 4}) is True
    assert "session_id" not in captured["json"]


def test_buffer_is_persisted_to_disk_and_restored(tmp_path, monkeypatch):
    def raise_error(*args, **kwargs):
        raise requests.RequestException("offline")

    monkeypatch.setattr("agent.api_client.requests.post", raise_error)

    client = make_client()
    client.session_id = "session-persist"
    client.send_metrics([{"active_seconds": 7}])

    buffer_file = tmp_path / "metrics_buffer.json"
    assert buffer_file.exists()

    restored = make_client()
    assert len(restored._buffer) == 1
    assert restored._buffer[0]["session_id"] == "session-persist"


def test_refresh_rotates_refresh_token(monkeypatch):
    client = make_client()
    client.refresh_token = "old-refresh"

    def fake_post(url, json=None, headers=None, timeout=None):
        return FakeResponse(200, {
            "access_token": "new-access",
            "refresh_token": "new-refresh",
        })

    monkeypatch.setattr("agent.api_client.requests.post", fake_post)
    assert client._refresh() is True
    assert client.access_token == "new-access"
    assert client.refresh_token == "new-refresh"
