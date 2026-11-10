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
