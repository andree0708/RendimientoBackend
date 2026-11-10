"""Tests for the agent configuration and credential handling."""

import json

from agent import config as config_module
from agent.config import AgentConfig


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_module, "CONFIG_FILE", tmp_path / "agent_config.json")


def test_password_is_never_written_to_disk(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    AgentConfig(email="agent@example.com", password="super-secret").save()

    raw = (tmp_path / "agent_config.json").read_text(encoding="utf-8")
    assert "super-secret" not in raw
    assert "password" not in json.loads(raw)

    loaded = AgentConfig.load()
    assert loaded.email == "agent@example.com"
    assert loaded.password == ""


def test_legacy_plaintext_password_is_removed_from_disk(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    config_file = tmp_path / "agent_config.json"
    config_file.write_text(
        json.dumps({"email": "agent@example.com", "password": "legacy-secret"}),
        encoding="utf-8",
    )

    loaded = AgentConfig.load()

    # Still usable for this run, but scrubbed from disk.
    assert loaded.password == "legacy-secret"
    raw = config_file.read_text(encoding="utf-8")
    assert "legacy-secret" not in raw
    assert "password" not in json.loads(raw)


def test_password_can_be_supplied_via_environment(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setenv("WORKSENSE_AGENT_PASSWORD", "env-secret")

    assert AgentConfig().resolve_password() == "env-secret"
