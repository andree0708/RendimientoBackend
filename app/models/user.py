"""User, role, and permission models with RBAC support."""

from datetime import datetime

from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, Table
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UTCDateTime, generate_uuid

# Association table for many-to-many User <-> Role
user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", String, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", String, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
)

# Association table for many-to-many Role <-> Permission
role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column("role_id", String, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column("permission_id", String, ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
)


class Role(TimestampMixin, Base):
    __tablename__ = "roles"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)

    users: Mapped[list["User"]] = relationship("User", secondary=user_roles, back_populates="roles")
    permissions: Mapped[list["Permission"]] = relationship(
        "Permission", secondary=role_permissions, back_populates="roles"
    )


class Permission(TimestampMixin, Base):
    __tablename__ = "permissions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)

    roles: Mapped[list["Role"]] = relationship(
        "Role", secondary=role_permissions, back_populates="permissions"
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    preferred_scale_max: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    failed_login_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(UTCDateTime(timezone=True), nullable=True)
    token_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    organization_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True
    )

    roles: Mapped[list[Role]] = relationship("Role", secondary=user_roles, back_populates="users")
    organization: Mapped["Organization | None"] = relationship(
        "Organization", back_populates="members"
    )
    teams: Mapped[list["TeamMember"]] = relationship("TeamMember", back_populates="user")
    work_sessions: Mapped[list["WorkSession"]] = relationship("WorkSession", back_populates="user")
    self_reports: Mapped[list["SelfReport"]] = relationship("SelfReport", back_populates="user")
    tasks: Mapped[list["Task"]] = relationship("Task", back_populates="user")
    recommendations: Mapped[list["Recommendation"]] = relationship(
        "Recommendation", back_populates="user"
    )
    notifications: Mapped[list["Notification"]] = relationship("Notification", back_populates="user")
    agent_devices: Mapped[list["AgentDevice"]] = relationship("AgentDevice", back_populates="user")


# Forward references resolved at import time by other modules
from app.models.organization import Organization  # noqa: E402
from app.models.compliance import AgentDevice  # noqa: E402
