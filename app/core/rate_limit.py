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
    """Rate-limit requests by client IP address."""

    def __init__(self, app, requests_per_minute: int = 120):
        super().__init__(app)
        self.limit = requests_per_minute
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._window = 60.0  # seconds

    async def dispatch(self, request: Request, call_next):
        # Skip rate limiting for health checks and docs
        if request.url.path in ("/health", "/docs", "/redoc", "/openapi.json"):
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        now = time.time()

        # Clean old entries outside the window
        self._requests[client_ip] = [
            ts for ts in self._requests[client_ip] if now - ts < self._window
        ]

        if len(self._requests[client_ip]) >= self.limit:
            return Response(
                content='{"error": "rate_limited", "detail": "Too many requests. Please slow down."}',
                status_code=429,
                media_type="application/json",
                headers={"Retry-After": "60"},
            )

        self._requests[client_ip].append(now)
        return await call_next(request)


def setup_rate_limiting(app):
    """Attach rate limiting middleware to the FastAPI app."""
    app.add_middleware(RateLimitMiddleware, requests_per_minute=settings.RATE_LIMIT_PER_MINUTE)
