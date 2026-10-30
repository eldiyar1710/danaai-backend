from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db_session, require_roles
from app.modules.organizations.models import Organization
from app.modules.organizations.repository import OrganizationRepository
from app.modules.organizations.schemas import (
    OrganizationCreate,
    OrganizationRead,
    OrganizationUpdate,
)
from app.modules.organizations.service import OrganizationService
from app.modules.users.models import User, UserRole

router = APIRouter(prefix="/organizations", tags=["organizations"])


def service(session: AsyncSession = Depends(get_db_session)) -> OrganizationService:
    return OrganizationService(OrganizationRepository(session))


@router.post("", response_model=OrganizationRead, status_code=status.HTTP_201_CREATED)
async def create_organization(
    data: OrganizationCreate,
    actor: User = Depends(require_roles(UserRole.SUPER_ADMIN)),
    organization_service: OrganizationService = Depends(service),
) -> Organization:
    return await organization_service.create(data)


@router.get("", response_model=list[OrganizationRead])
async def list_organizations(
    actor: User = Depends(require_roles(UserRole.SUPER_ADMIN)),
    session: AsyncSession = Depends(get_db_session),
) -> list[Organization]:
    return await OrganizationRepository(session).list()


@router.patch("/{organization_id}", response_model=OrganizationRead)
async def update_organization(
    organization_id: UUID,
    data: OrganizationUpdate,
    actor: User = Depends(require_roles(UserRole.SUPER_ADMIN)),
    organization_service: OrganizationService = Depends(service),
) -> Organization:
    return await organization_service.update(organization_id, data)
