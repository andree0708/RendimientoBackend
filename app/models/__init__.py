"""SQLAlchemy ORM models for WorkSense AI.

Importing this package registers every model with the ``Base`` metadata
so that ``init_db()`` and Alembic can see all tables.
"""

from app.models.base import TimestampMixin
from app.models.user import Role, Permission, User, user_roles, role_permissions
from app.models.organization import Organization, Team, TeamMember
from app.models.session import ApplicationCategory, WorkSession, ActivityMetric
from app.models.task import Task, TaskResult
from app.models.self_report import SelfReport
from app.models.ai import (
    FatigueAssessment,
    PerformancePrediction,
    ModelVersion,
    ModelEvaluation,
)
from app.models.recommendation import Recommendation
from app.models.notification import Notification
from app.models.compliance import ConsentRecord, AgentDevice, AuditLog
from app.models.auth import RevokedRefreshToken

__all__ = [
    "TimestampMixin",
    "Role",
    "Permission",
    "User",
    "user_roles",
    "role_permissions",
    "Organization",
    "Team",
    "TeamMember",
    "ApplicationCategory",
    "WorkSession",
    "ActivityMetric",
    "Task",
    "TaskResult",
    "SelfReport",
    "FatigueAssessment",
    "PerformancePrediction",
    "ModelVersion",
    "ModelEvaluation",
    "Recommendation",
    "Notification",
    "ConsentRecord",
    "AgentDevice",
    "AuditLog",
    "RevokedRefreshToken",
]
