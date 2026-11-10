"""Unit tests for the rate-limit middleware (direct ASGI, no test pollution)."""

from contextlib import contextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.core.rate_limit import RateLimitMiddleware


@contextmanager
def rate_limiting_enabled():
    """Force the flag on inside the test body (order-independent)."""
    from app.core.config import settings

    previous = settings.RATE_LIMIT_ENABLED
    settings.RATE_LIMIT_ENABLED = True
    try:
        yield
    finally:
        settings.RATE_LIMIT_ENABLED = previous


def _app_with_limits(general: int = 120, auth: int = 2) -> FastAPI:
    app = FastAPI()

    @app.get("/api/v1/auth/login")
    async def fake_login():
        return JSONResponse({"ok": True})

    @app.get("/api/v1/sessions")
    async def fake_sessions():
        return JSONResponse({"ok": True})

    app.add_middleware(
        RateLimitMiddleware,
        requests_per_minute=general,
        auth_requests_per_minute=auth,
    )
    return app


def test_auth_endpoints_get_stricter_limit():
    with rate_limiting_enabled():
        client = TestClient(_app_with_limits(auth=2))
        assert client.get("/api/v1/auth/login").status_code == 200
        assert client.get("/api/v1/auth/login").status_code == 200
        resp = client.get("/api/v1/auth/login")
        assert resp.status_code == 429
        assert resp.headers.get("Retry-After") == "60"


def test_general_endpoints_use_general_limit():
    with rate_limiting_enabled():
        client = TestClient(_app_with_limits(general=3, auth=100))
        for _ in range(3):
            assert client.get("/api/v1/sessions").status_code == 200
        assert client.get("/api/v1/sessions").status_code == 429


def test_auth_and_general_buckets_are_independent():
    with rate_limiting_enabled():
        client = TestClient(_app_with_limits(general=1, auth=1))
        assert client.get("/api/v1/auth/login").status_code == 200
        # General bucket is separate: still allowed.
        assert client.get("/api/v1/sessions").status_code == 200
        # But each bucket enforces its own limit.
        assert client.get("/api/v1/auth/login").status_code == 429
        assert client.get("/api/v1/sessions").status_code == 429


def test_disabled_flag_bypasses_limits(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", False)
    client = TestClient(_app_with_limits(general=1, auth=1))
    for _ in range(5):
        assert client.get("/api/v1/auth/login").status_code == 200
        assert client.get("/api/v1/sessions").status_code == 200
