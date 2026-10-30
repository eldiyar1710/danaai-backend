from datetime import UTC, datetime

from fastapi import HTTPException, status

from app.core.config import Settings
from app.core.security import (
    TokenError,
    create_token,
    decode_token,
    hash_password,
    hash_refresh_token,
    needs_password_rehash,
    verify_password,
)
from app.modules.auth.models import RefreshSession
from app.modules.auth.repository import RefreshSessionRepository
from app.modules.auth.schemas import TokenPair
from app.modules.users.models import User
from app.modules.users.repository import UserRepository


class AuthenticationService:
    def __init__(
        self,
        users: UserRepository,
        refresh_sessions: RefreshSessionRepository,
        settings: Settings,
    ) -> None:
        self.users = users
        self.refresh_sessions = refresh_sessions
        self.settings = settings

    def unauthorized(self) -> HTTPException:
        return HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials or refresh token",
        )

    async def login(self, email: str, password: str) -> TokenPair:
        user = await self.users.get_by_email(email)
        if (
            user is None
            or not user.is_active
            or not verify_password(password, user.hashed_password)
        ):
            raise self.unauthorized()
        if needs_password_rehash(user.hashed_password):
            user.hashed_password = hash_password(password)
        tokens = await self._issue_pair(user)
        await self.users.session.commit()
        return tokens

    async def refresh(self, raw_refresh_token: str) -> TokenPair:
        try:
            claims = decode_token(raw_refresh_token, self.settings, "refresh")
        except TokenError as exc:
            raise self.unauthorized() from exc
        stored = await self.refresh_sessions.get_active_for_update(
            hash_refresh_token(raw_refresh_token)
        )
        if stored is None or stored.user_id != claims.sub or stored.expires_at <= datetime.now(UTC):
            raise self.unauthorized()
        user = await self.users.get_by_id(claims.sub)
        if user is None or not user.is_active:
            raise self.unauthorized()
        await self.refresh_sessions.revoke(stored, datetime.now(UTC))
        tokens = await self._issue_pair(user)
        await self.users.session.commit()
        return tokens

    async def logout(self, raw_refresh_token: str) -> None:
        stored = await self.refresh_sessions.get_active_for_update(
            hash_refresh_token(raw_refresh_token)
        )
        if stored is not None:
            await self.refresh_sessions.revoke(stored, datetime.now(UTC))
            await self.users.session.commit()

    async def _issue_pair(self, user: User) -> TokenPair:
        access, _ = create_token(
            user_id=user.id,
            role=user.role,
            organization_id=user.organization_id,
            token_type="access",
            settings=self.settings,
        )
        refresh, claims = create_token(
            user_id=user.id,
            role=user.role,
            organization_id=user.organization_id,
            token_type="refresh",
            settings=self.settings,
        )
        await self.refresh_sessions.add(
            RefreshSession(
                user_id=user.id,
                token_hash=hash_refresh_token(refresh),
                expires_at=claims.exp,
            )
        )
        return TokenPair(
            access_token=access,
            refresh_token=refresh,
            expires_in=self.settings.access_token_expire_minutes * 60,
        )
