from unittest.mock import AsyncMock
from uuid import uuid4

from app.modules.auth.policy import user_has_active_tenant
from app.modules.users.models import User, UserRole


def _user(role: UserRole, organization_id: object = None) -> User:
    return User(
        email="user@example.com",
        hashed_password="hash",
        first_name="Test",
        last_name="User",
        role=role,
        organization_id=organization_id,
        is_active=True,
    )


async def test_super_admin_does_not_require_an_organization() -> None:
    session = AsyncMock()

    assert await user_has_active_tenant(session, _user(UserRole.SUPER_ADMIN)) is True
    session.scalar.assert_not_awaited()


async def test_organization_user_requires_active_organization() -> None:
    session = AsyncMock()
    session.scalar.return_value = True

    assert await user_has_active_tenant(session, _user(UserRole.USER, uuid4())) is True
    session.scalar.assert_awaited_once()


async def test_inactive_or_missing_organization_is_rejected() -> None:
    session = AsyncMock()
    session.scalar.return_value = False

    assert await user_has_active_tenant(session, _user(UserRole.ORG_ADMIN, uuid4())) is False
    assert await user_has_active_tenant(session, _user(UserRole.USER)) is False
