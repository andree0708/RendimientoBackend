"""Application configuration loaded from environment variables."""

from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration for the WorkSense AI backend.

    Values are read from environment variables or a .env file.
    A SQLite database is used by default so the project runs without
    requiring a PostgreSQL installation; switch the ``DATABASE_URL``
    to a postgresql connection string for production.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- Application ----
    APP_NAME: str = "WorkSense AI"
    APP_ENV: str = "development"
    DEBUG: bool = True
    API_V1_PREFIX: str = "/api/v1"

    # ---- Database ----
    DATABASE_URL: str = "sqlite:///./worksense.db"

    # ---- Security ----
    SECRET_KEY: str = "change-me-to-a-long-random-secret-key-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # ---- CORS ----
    BACKEND_CORS_ORIGINS: str = "http://localhost:4200,http://localhost:3000"

    # ---- WebSocket ----
    WS_HEARTBEAT_INTERVAL_SECONDS: int = 30
    WS_RECONNECT_MAX_RETRIES: int = 5

    # ---- Rate Limiting ----
    RATE_LIMIT_PER_MINUTE: int = 120

    # ---- AI Module ----
    AI_MODELS_DIR: str = "models/saved"
    AI_USE_DEMO_DATA: bool = True
    AI_MIN_SAMPLES_FOR_TRAINING: int = 50
    AI_PREDICTION_HORIZON_MINUTES: int = 30

    # ---- Agent ----
    AGENT_TOKEN: str = ""
    AGENT_METRICS_BATCH_SIZE: int = 20
    AGENT_COLLECTION_INTERVAL_SECONDS: int = 60

    @property
    def cors_origins(self) -> List[str]:
        """Return CORS origins as a list, trimmed of whitespace."""
        return [
            origin.strip()
            for origin in self.BACKEND_CORS_ORIGINS.split(",")
            if origin.strip()
        ]

    @property
    def is_sqlite(self) -> bool:
        """True when the configured database is SQLite."""
        return self.DATABASE_URL.startswith("sqlite")

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()


settings = get_settings()
