"""Organization routes."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_pagination
from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.pagination import paginate
from app.models.user import User
from app.schemas.organization import OrganizationCreate, OrganizationPage, OrganizationRead
from app.schemas.team import TeamCreate, TeamPage, TeamRead
from app.services import organization_service

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.post("", response_model=OrganizationRead, status_code=201)
def create_organization(
    data: OrganizationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return organization_service.create_organization(db, data)


@router.get("", response_model=OrganizationPage)
def list_organizations(
    pagination=Depends(get_pagination),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    orgs, total = organization_service.list_organizations(db, pagination.offset, pagination.limit)
    return paginate([OrganizationRead.model_validate(o) for o in orgs], total, pagination)


@router.get("/{org_id}", response_model=OrganizationRead)
def get_organization(org_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return organization_service.get_organization(db, org_id)


@router.get("/{org_id}/teams", response_model=TeamPage)
def list_org_teams(
    org_id: str,
    pagination=Depends(get_pagination),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    teams, total = organization_service.list_teams(db, org_id, pagination.offset, pagination.limit)
    return paginate([TeamRead.model_validate(t) for t in teams], total, pagination)


@router.post("/teams", response_model=TeamRead, status_code=201)
def create_team(
    data: TeamCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return organization_service.create_team(db, data)
