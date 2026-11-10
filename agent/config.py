"""Agent configuration."""

import json
import os
from dataclasses import dataclass, asdict
from pathlib import Path


CONFIG_DIR = Path.home() / ".worksense"
CONFIG_FILE = CONFIG_DIR / "agent_config.json"


@dataclass
class AgentConfig:
    """Persistent agent configuration stored in the user's home directory."""

    backend_url: str = "http://127.0.0.1:8000"
    ws_url: str = "ws://127.0.0.1:8000/ws"
    email: str = ""
    password: str = ""
    collection_interval: int = 60  # seconds
    batch_size: int = 20
    idle_threshold: int = 300  # seconds before considered idle
    enable_app_tracking: bool = True
    enable_local_buffer: bool = True
    max_buffer_size: int = 1000

    @classmethod
    def load(cls) -> "AgentConfig":
        """Load config from disk, or return defaults."""
        if CONFIG_FILE.exists():
            try:
                data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                return cls(**data)
            except (json.JSONDecodeError, TypeError):
                pass
        return cls()

    def save(self) -> None:
        """Persist config to disk."""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(
            json.dumps(asdict(self), indent=2), encoding="utf-8"
        )
