"""Simple in-memory rate limiting middleware.

Limits requests per IP address per minute window.  Uses a sliding
window counter to avoid the need for Redis or external stores.
"""

import time
from collections import defaultdict

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate-limit requests by client IP address.

    Auth endpoints get a stricter limit to slow down credential stuffing;
    everything else uses the general per-minute budget.
    """

    def __init__(
        self,
        app,
        requests_per_minute: int = 120,
        auth_requests_per_minute: int = 10,
    ):
        super().__init__(app)
        self.limit = requests_per_minute
        self.auth_limit = auth_requests_per_minute
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._window = 60.0  # seconds

    async def dispatch(self, request: Request, call_next):
        # Disabled in tests via RATE_LIMIT_ENABLED=False.
        if not settings.RATE_LIMIT_ENABLED:
            return await call_next(request)
        # Skip rate limiting for health checks and docs
        if request.url.path in (
            "/health",
            "/health/detailed",
            "/docs",
            "/redoc",
            "/openapi.json",
        ):
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        is_auth = request.url.path.startswith("/api/v1/auth/")
        limit = self.auth_limit if is_auth else self.limit
        key = f"{client_ip}:{'auth' if is_auth else 'api'}"
        now = time.time()

        # Clean old entries outside the window
        self._requests[key] = [
            ts for ts in self._requests[key] if now - ts < self._window
        ]

        if len(self._requests[key]) >= limit:
            return Response(
                content='{"error": "rate_limited", "detail": "Too many requests. Please slow down."}',
                status_code=429,
                media_type="application/json",
                headers={"Retry-After": "60"},
            )

        self._requests[key].append(now)
        return await call_next(request)


def setup_rate_limiting(app):
    """Attach rate limiting middleware to the FastAPI app."""
    app.add_middleware(
        RateLimitMiddleware,
        requests_per_minute=settings.RATE_LIMIT_PER_MINUTE,
        auth_requests_per_minute=settings.RATE_LIMIT_AUTH_PER_MINUTE,
    )
