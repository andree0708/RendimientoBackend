"""Organization and team management service."""

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.models.organization import Organization, Team
from app.models.user import User
from app.schemas.organization import OrganizationCreate
from app.schemas.team import TeamCreate


def create_organization(db: Session, data: OrganizationCreate) -> Organization:
    org = Organization(name=data.name, description=data.description)
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


def list_organizations(db: Session, offset: int = 0, limit: int = 20) -> tuple[list[Organization], int]:
    query = db.query(Organization)
    total = query.count()
    return query.offset(offset).limit(limit).all(), total


def get_organization(db: Session, org_id: str) -> Organization:
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        raise NotFoundError("Organización no encontrada")
    return org


def create_team(db: Session, data: TeamCreate) -> Team:
    org = get_organization(db, data.organization_id)
    team = Team(name=data.name, description=data.description, organization_id=org.id)
    db.add(team)
    db.commit()
    db.refresh(team)
    return team


def list_teams(db: Session, org_id: str | None = None, offset: int = 0, limit: int = 20) -> tuple[list[Team], int]:
    query = db.query(Team)
    if org_id:
        query = query.filter(Team.organization_id == org_id)
    total = query.count()
    return query.offset(offset).limit(limit).all(), total


def add_member(db: Session, team_id: str, user_id: str, role_label: str = "member") -> None:
    from app.models.organization import TeamMember

    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise NotFoundError("Equipo no encontrado")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise NotFoundError("Usuario no encontrado")

    existing = (
        db.query(TeamMember)
        .filter(TeamMember.team_id == team_id, TeamMember.user_id == user_id)
        .first()
    )
    if existing:
        existing.role_label = role_label
    else:
        member = TeamMember(team_id=team_id, user_id=user_id, role_label=role_label)
        db.add(member)
    db.commit()
