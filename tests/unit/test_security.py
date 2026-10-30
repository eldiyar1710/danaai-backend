from uuid import uuid4

import pytest

from app.core.config import Settings
from app.core.security import (
    TokenError,
    create_token,
    decode_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from app.modules.users.models import UserRole


def test_argon2_password_roundtrip() -> None:
    password_hash = hash_password("a-strong-test-password")
    assert password_hash.startswith("$argon2")
    assert verify_password("a-strong-test-password", password_hash)
    assert not verify_password("wrong-password", password_hash)


def test_access_token_roundtrip() -> None:
    settings = Settings()
    user_id = uuid4()
    organization_id = uuid4()
    token, _ = create_token(
        user_id=user_id,
        role=UserRole.USER,
        organization_id=organization_id,
        token_type="access",
        settings=settings,
    )
    claims = decode_token(token, settings, "access")
    assert claims.sub == user_id
    assert claims.organization_id == organization_id


def test_refresh_token_cannot_be_used_as_access_token() -> None:
    settings = Settings()
    token, _ = create_token(
        user_id=uuid4(),
        role=UserRole.SUPER_ADMIN,
        organization_id=None,
        token_type="refresh",
        settings=settings,
    )
    with pytest.raises(TokenError):
        decode_token(token, settings, "access")


def test_refresh_hash_does_not_store_raw_token() -> None:
    raw = "refresh-token-value"
    digest = hash_refresh_token(raw)
    assert digest != raw
    assert len(digest) == 64
