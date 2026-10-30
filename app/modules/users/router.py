from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db_session, require_roles
from app.modules.users.models import User, UserRole
from app.modules.users.repository import UserRepository
from app.modules.users.schemas import UserCreate, UserRead, UserUpdate
from app.modules.users.service import UserService

router = APIRouter(prefix="/users", tags=["users"])


def service(session: AsyncSession = Depends(get_db_session)) -> UserService:
    return UserService(UserRepository(session))


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(
    data: UserCreate,
    actor: User = Depends(require_roles(UserRole.SUPER_ADMIN, UserRole.ORG_ADMIN)),
    user_service: UserService = Depends(service),
) -> User:
    return await user_service.create(actor, data)


@router.get("", response_model=list[UserRead])
async def list_users(
    organization_id: UUID | None = None,
    actor: User = Depends(require_roles(UserRole.SUPER_ADMIN, UserRole.ORG_ADMIN)),
    user_service: UserService = Depends(service),
) -> list[User]:
    return await user_service.list(actor, organization_id)


@router.patch("/{user_id}", response_model=UserRead)
async def update_user(
    user_id: UUID,
    data: UserUpdate,
    actor: User = Depends(require_roles(UserRole.SUPER_ADMIN, UserRole.ORG_ADMIN)),
    user_service: UserService = Depends(service),
) -> User:
    return await user_service.update(actor, user_id, data)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: UUID,
    actor: User = Depends(require_roles(UserRole.SUPER_ADMIN, UserRole.ORG_ADMIN)),
    user_service: UserService = Depends(service),
) -> Response:
    await user_service.deactivate(actor, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
