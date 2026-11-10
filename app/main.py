"""WorkSense AI — FastAPI application entry point.

Run locally:  uvicorn app.main:app --reload
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.core.database import init_db
from app.core.exceptions import AppException, app_exception_handler
from app.core.rate_limit import setup_rate_limiting
from app.websocket.manager import ws_manager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    # Startup: create tables if they don't exist (dev convenience)
    logger.info("Initialising database tables...")
    init_db()

    # Start the WebSocket heartbeat background task
    heartbeat_task = asyncio.create_task(ws_manager.heartbeat_loop())
    logger.info("WebSocket heartbeat started (interval=%ds)", 30)

    yield

    # Shutdown: cancel heartbeat
    heartbeat_task.cancel()
    logger.info("Shutdown complete.")


app = FastAPI(
    title=settings.APP_NAME,
    description="Intelligent system for fatigue and workplace performance analysis using AI.",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate limiting
setup_rate_limiting(app)


class SecurityHeadersMiddleware:
    """Add minimal security headers to every response."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = dict(message.get("headers", []))
                headers[b"x-content-type-options"] = b"nosniff"
                headers[b"x-frame-options"] = b"DENY"
                headers[b"referrer-policy"] = b"no-referrer"
                # Docs UI needs inline scripts; keep CSP permissive but present.
                headers[b"content-security-policy"] = (
                    b"default-src 'self'; "
                    b"script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                    b"style-src 'self' 'unsafe-inline'; img-src 'self' data:;"
                )
                message["headers"] = list(headers.items())
            await send(message)

        await self.app(scope, receive, send_with_headers)


app.add_middleware(SecurityHeadersMiddleware)

# Exception handlers
app.add_exception_handler(AppException, app_exception_handler)

# Register the API router under /api/v1 (REST) and /ws (WebSocket at root)
app.include_router(api_router, prefix=settings.API_V1_PREFIX)
# WebSocket needs to be at root level (not under /api/v1)
from app.api.routes import ws as ws_route  # noqa: E402

app.include_router(ws_route.router)


@app.get("/health")
async def health():
    """Simple health-check endpoint."""
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "version": "0.1.0",
        "ws_connections": ws_manager.connection_count(),
    }


@app.get("/health/detailed")
async def health_detailed():
    """Deeper health check: DB connectivity and models directory."""
    from pathlib import Path

    from sqlalchemy import text

    from app.core.config import settings as live_settings
    from app.core.database import SessionLocal

    db_ok = False
    db_error: str | None = None
    try:
        session = SessionLocal()
        try:
            session.execute(text("SELECT 1"))
            db_ok = True
        finally:
            session.close()
    except Exception as exc:  # pragma: no cover - environment dependent
        db_error = str(exc)

    models_path = Path(live_settings.AI_MODELS_DIR)
    try:
        models_path.mkdir(parents=True, exist_ok=True)
        models_writable = True
        models_error: str | None = None
    except Exception as exc:  # pragma: no cover - environment dependent
        models_writable = False
        models_error = str(exc)

    degraded = not db_ok or not models_writable
    return {
        "status": "degraded" if degraded else "ok",
        "app": live_settings.APP_NAME,
        "version": "0.1.0",
        "ws_connections": ws_manager.connection_count(),
        "database": {"ok": db_ok, "error": db_error},
        "models_dir": {
            "path": str(models_path),
            "writable": models_writable,
            "error": models_error,
        },
    }
