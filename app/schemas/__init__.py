"""Pydantic schemas (request/response models) for the API."""

from app.schemas.common import Page, PageMeta
from app.schemas.auth import Token, TokenPayload, LoginRequest, RegisterRequest, RefreshRequest
from app.schemas.user import UserRead, UserUpdate, UserCreate
from app.schemas.organization import OrganizationRead, OrganizationCreate
from app.schemas.team import TeamRead, TeamCreate
from app.schemas.session import WorkSessionRead, WorkSessionCreate, WorkSessionUpdate
from app.schemas.metrics import ActivityMetricRead, ActivityMetricBatch
from app.schemas.task import TaskRead, TaskCreate, TaskUpdate, TaskResultRead
from app.schemas.self_report import SelfReportRead, SelfReportCreate
from app.schemas.ai import (
    FatigueAssessmentRead,
    PerformancePredictionRead,
    ModelVersionRead,
    ModelEvaluationRead,
    TrainingRequest,
    TrainingResponse,
)
from app.schemas.recommendation import RecommendationRead, RecommendationUpdate
from app.schemas.notification import NotificationRead
from app.schemas.websocket import WSEvent, WSEnvelope

__all__ = [
    "Page",
    "PageMeta",
    "Token",
    "TokenPayload",
    "LoginRequest",
    "RegisterRequest",
    "RefreshRequest",
    "UserRead",
    "UserUpdate",
    "UserCreate",
    "OrganizationRead",
    "OrganizationCreate",
    "TeamRead",
    "TeamCreate",
    "WorkSessionRead",
    "WorkSessionCreate",
    "WorkSessionUpdate",
    "ActivityMetricRead",
    "ActivityMetricBatch",
    "TaskRead",
    "TaskCreate",
    "TaskUpdate",
    "TaskResultRead",
    "SelfReportRead",
    "SelfReportCreate",
    "FatigueAssessmentRead",
    "PerformancePredictionRead",
    "ModelVersionRead",
    "ModelEvaluationRead",
    "TrainingRequest",
    "TrainingResponse",
    "RecommendationRead",
    "RecommendationUpdate",
    "NotificationRead",
    "WSEvent",
    "WSEnvelope",
]
