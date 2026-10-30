from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.organizations.models import Organization


class OrganizationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, organization_id: UUID) -> Organization | None:
        return await self.session.get(Organization, organization_id)

    async def list(self) -> list[Organization]:
        statement = select(Organization).order_by(Organization.created_at.desc())
        return list((await self.session.scalars(statement)).all())

    async def add(self, organization: Organization) -> Organization:
        self.session.add(organization)
        await self.session.flush()
        await self.session.refresh(organization)
        return organization
