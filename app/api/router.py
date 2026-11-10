"""Main API router that aggregates all domain routers."""

from fastapi import APIRouter

from app.api.routes import (
    admin,
    ai,
    auth,
    metrics,
    notifications,
    organizations,
    recommendations,
    self_reports,
    sessions,
    tasks,
    users,
    ws,
)

api_router = APIRouter()

# Register all domain routers
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(organizations.router)
api_router.include_router(sessions.router)
api_router.include_router(metrics.router)
api_router.include_router(tasks.router)
api_router.include_router(self_reports.router)
api_router.include_router(ai.router)
api_router.include_router(recommendations.router)
api_router.include_router(notifications.router)
api_router.include_router(admin.router)

# WebSocket endpoint (not under /api/v1 prefix)
api_router.include_router(ws.router)
