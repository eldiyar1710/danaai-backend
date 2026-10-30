from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.users.models import User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, user_id: UUID) -> User | None:
        return await self.session.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        statement = select(User).where(User.email == email.lower())
        return await self.session.scalar(statement)

    async def list(self, organization_id: UUID | None = None) -> list[User]:
        statement = select(User).order_by(User.created_at.desc())
        if organization_id is not None:
            statement = statement.where(User.organization_id == organization_id)
        return list((await self.session.scalars(statement)).all())

    async def add(self, user: User) -> User:
        self.session.add(user)
        await self.session.flush()
        await self.session.refresh(user)
        return user
