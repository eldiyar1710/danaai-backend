from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.dependencies import get_app_settings, get_current_user, get_db_session
from app.modules.auth.repository import RefreshSessionRepository
from app.modules.auth.schemas import LoginRequest, MeResponse, RefreshRequest, TokenPair
from app.modules.auth.service import AuthenticationService
from app.modules.users.models import User
from app.modules.users.repository import UserRepository

router = APIRouter(prefix="/auth", tags=["auth"])


def service(
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_app_settings),
) -> AuthenticationService:
    return AuthenticationService(
        UserRepository(session), RefreshSessionRepository(session), settings
    )


@router.post("/login", response_model=TokenPair)
async def login(
    data: LoginRequest, auth_service: AuthenticationService = Depends(service)
) -> TokenPair:
    return await auth_service.login(data.email, data.password)


@router.post("/refresh", response_model=TokenPair)
async def refresh(
    data: RefreshRequest, auth_service: AuthenticationService = Depends(service)
) -> TokenPair:
    return await auth_service.refresh(data.refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    data: RefreshRequest, auth_service: AuthenticationService = Depends(service)
) -> Response:
    await auth_service.logout(data.refresh_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=MeResponse)
async def me(user: User = Depends(get_current_user)) -> User:
    return user
