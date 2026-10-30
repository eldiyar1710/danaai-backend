from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.modules.organizations.models import Organization
from app.modules.organizations.repository import OrganizationRepository
from app.modules.organizations.schemas import OrganizationCreate, OrganizationUpdate


class OrganizationService:
    def __init__(self, repository: OrganizationRepository) -> None:
        self.repository = repository

    async def create(self, data: OrganizationCreate) -> Organization:
        organization = Organization(name=data.name.strip(), description=data.description)
        try:
            await self.repository.add(organization)
            await self.repository.session.commit()
        except IntegrityError as exc:
            await self.repository.session.rollback()
            raise HTTPException(status_code=409, detail="Organization name already exists") from exc
        return organization

    async def update(self, organization_id: UUID, data: OrganizationUpdate) -> Organization:
        organization = await self.repository.get(organization_id)
        if organization is None:
            raise HTTPException(status_code=404, detail="Organization not found")
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(organization, field, value.strip() if field == "name" else value)
        try:
            await self.repository.session.commit()
            await self.repository.session.refresh(organization)
        except IntegrityError as exc:
            await self.repository.session.rollback()
            raise HTTPException(status_code=409, detail="Organization name already exists") from exc
        return organization
