from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.core.security import hash_password
from app.modules.users.models import User, UserRole
from app.modules.users.repository import UserRepository
from app.modules.users.schemas import UserCreate, UserUpdate


class UserService:
    def __init__(self, repository: UserRepository) -> None:
        self.repository = repository

    async def create(self, actor: User, data: UserCreate) -> User:
        if actor.role == UserRole.ORG_ADMIN:
            if data.organization_id != actor.organization_id or data.role != UserRole.USER:
                raise HTTPException(status_code=403, detail="Cannot create this user")
        elif actor.role != UserRole.SUPER_ADMIN:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        user = User(
            organization_id=data.organization_id,
            email=data.email.lower(),
            hashed_password=hash_password(data.password),
            first_name=data.first_name,
            last_name=data.last_name,
            role=data.role,
            is_active=True,
        )
        try:
            await self.repository.add(user)
            await self.repository.session.commit()
        except IntegrityError as exc:
            await self.repository.session.rollback()
            raise HTTPException(status_code=409, detail="Email already exists") from exc
        return user

    async def list(self, actor: User, organization_id: UUID | None) -> list[User]:
        if actor.role == UserRole.SUPER_ADMIN:
            return await self.repository.list(organization_id)
        if actor.role == UserRole.ORG_ADMIN and actor.organization_id is not None:
            return await self.repository.list(actor.organization_id)
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    async def update(self, actor: User, user_id: UUID, data: UserUpdate) -> User:
        target = await self.repository.get_by_id(user_id)
        if target is None:
            raise HTTPException(status_code=404, detail="User not found")
        if actor.role == UserRole.ORG_ADMIN:
            if target.organization_id != actor.organization_id or target.role != UserRole.USER:
                raise HTTPException(status_code=403, detail="Cannot update this user")
            if data.role is not None and data.role != UserRole.USER:
                raise HTTPException(status_code=403, detail="Cannot grant administrative role")
        elif actor.role != UserRole.SUPER_ADMIN:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        if target.id == actor.id and data.is_active is False:
            raise HTTPException(status_code=400, detail="Cannot deactivate current user")
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(target, field, value)
        await self.repository.session.commit()
        await self.repository.session.refresh(target)
        return target

    async def deactivate(self, actor: User, user_id: UUID) -> None:
        await self.update(actor, user_id, UserUpdate(is_active=False))
