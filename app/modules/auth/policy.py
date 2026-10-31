from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.organizations.models import Organization
from app.modules.users.models import User, UserRole


async def user_has_active_tenant(session: AsyncSession, user: User) -> bool:
    """Require every organization user to belong to an active organization."""
    if user.role == UserRole.SUPER_ADMIN:
        return user.organization_id is None
    if user.organization_id is None:
        return False
    is_active = await session.scalar(
        select(Organization.is_active).where(Organization.id == user.organization_id)
    )
    return is_active is True
