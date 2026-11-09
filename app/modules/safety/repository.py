from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.models import (
    EmployeeSafetyProfile,
    EmployeeSafetyStage,
    EmployeeWorkScope,
)
from app.modules.users.models import User


class SafetyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_profile_by_user(self, user_id: UUID) -> EmployeeSafetyProfile | None:
        return await self.session.scalar(
            select(EmployeeSafetyProfile).where(EmployeeSafetyProfile.user_id == user_id)
        )

    async def list_profiles(self, organization_id: UUID | None) -> list[EmployeeSafetyProfile]:
        statement = select(EmployeeSafetyProfile).order_by(EmployeeSafetyProfile.created_at)
        if organization_id is not None:
            statement = statement.where(EmployeeSafetyProfile.organization_id == organization_id)
        return list((await self.session.scalars(statement)).all())

    async def get_user(self, user_id: UUID) -> User | None:
        return await self.session.get(User, user_id)

    async def list_stages(self, profile_id: UUID) -> list[EmployeeSafetyStage]:
        statement = (
            select(EmployeeSafetyStage)
            .where(EmployeeSafetyStage.profile_id == profile_id)
            .order_by(EmployeeSafetyStage.stage_order)
        )
        return list((await self.session.scalars(statement)).all())

    async def get_stage(self, profile_id: UUID, code: str) -> EmployeeSafetyStage | None:
        return await self.session.scalar(
            select(EmployeeSafetyStage).where(
                EmployeeSafetyStage.profile_id == profile_id,
                EmployeeSafetyStage.code == code,
            )
        )

    async def list_scopes(self, profile_id: UUID) -> list[EmployeeWorkScope]:
        statement = (
            select(EmployeeWorkScope)
            .where(EmployeeWorkScope.profile_id == profile_id)
            .order_by(EmployeeWorkScope.code)
        )
        return list((await self.session.scalars(statement)).all())
