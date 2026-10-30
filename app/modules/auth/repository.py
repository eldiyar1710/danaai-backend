from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import RefreshSession


class RefreshSessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_active_for_update(self, token_hash: str) -> RefreshSession | None:
        statement = (
            select(RefreshSession)
            .where(
                RefreshSession.token_hash == token_hash,
                RefreshSession.revoked_at.is_(None),
            )
            .with_for_update()
        )
        return await self.session.scalar(statement)

    async def add(self, refresh_session: RefreshSession) -> None:
        self.session.add(refresh_session)
        await self.session.flush()

    async def revoke(self, refresh_session: RefreshSession, revoked_at: datetime) -> None:
        refresh_session.revoked_at = revoked_at
        await self.session.flush()
