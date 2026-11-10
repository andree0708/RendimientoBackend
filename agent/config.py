"""Agent configuration.

The account password is never written to disk. It is read from the
``WORKSENSE_AGENT_PASSWORD`` environment variable or prompted for at runtime.
Older versions stored it in plaintext; ``load()`` migrates those files by
rewriting them without the password.
"""

import json
import logging
import os
from dataclasses import asdict, dataclass
from pathlib import Path


CONFIG_DIR = Path.home() / ".worksense"
CONFIG_FILE = CONFIG_DIR / "agent_config.json"
PASSWORD_ENV = "WORKSENSE_AGENT_PASSWORD"

logger = logging.getLogger(__name__)


@dataclass
class AgentConfig:
    """Persistent agent configuration stored in the user's home directory."""

    backend_url: str = "http://127.0.0.1:8000"
    ws_url: str = "ws://127.0.0.1:8000/ws"
    email: str = ""
    # Runtime only — excluded from the on-disk representation.
    password: str = ""
    collection_interval: int = 60  # seconds
    batch_size: int = 20
    idle_threshold: int = 300  # seconds before considered idle
    enable_app_tracking: bool = True
    enable_local_buffer: bool = True
    max_buffer_size: int = 1000

    @classmethod
    def load(cls) -> "AgentConfig":
        """Load config from disk, or return defaults.

        Any legacy plaintext password is moved into memory and immediately
        removed from the file.
        """
        if CONFIG_FILE.exists():
            try:
                data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                legacy_password = data.pop("password", "")
                config = cls(**data)
                if legacy_password:
                    config.password = legacy_password
                    logger.warning(
                        "Removed a plaintext password from %s. Set %s or "
                        "run 'agent setup' to provide it at runtime.",
                        CONFIG_FILE,
                        PASSWORD_ENV,
                    )
                    config.save()
                return config
            except (json.JSONDecodeError, TypeError):
                pass
        return cls()

    def save(self) -> None:
        """Persist config to disk without ever writing the password."""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        payload = asdict(self)
        payload.pop("password", None)
        CONFIG_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        try:
            os.chmod(CONFIG_FILE, 0o600)
        except OSError:
            # Windows and some filesystems do not support chmod; the file is
            # still created inside the user's home directory.
            pass

    def resolve_password(self) -> str:
        """Return the password from memory or the environment."""
        return self.password or os.environ.get(PASSWORD_ENV, "")
