"""Organization and team models."""

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, generate_uuid


class Organization(TimestampMixin, Base):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)

    members: Mapped[list["User"]] = relationship("User", back_populates="organization")
    teams: Mapped[list["Team"]] = relationship(
        "Team", back_populates="organization", cascade="all, delete-orphan"
    )


class Team(TimestampMixin, Base):
    __tablename__ = "teams"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)

    organization_id: Mapped[str] = mapped_column(
        String, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )

    organization: Mapped[Organization] = relationship("Organization", back_populates="teams")
    members: Mapped[list["TeamMember"]] = relationship(
        "TeamMember", back_populates="team", cascade="all, delete-orphan"
    )


class TeamMember(TimestampMixin, Base):
    """Association between a user and a team with a role label."""

    __tablename__ = "team_members"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    team_id: Mapped[str] = mapped_column(
        String, ForeignKey("teams.id", ondelete="CASCADE"), nullable=False
    )
    role_label: Mapped[str] = mapped_column(String(100), nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="teams")
    team: Mapped[Team] = relationship("Team", back_populates="members")


# Resolve forward reference
from app.models.user import User  # noqa: E402
