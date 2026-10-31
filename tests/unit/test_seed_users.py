import pytest
from pydantic import ValidationError

from scripts.seed_users import SeedIdentity, UserSeedConfig


def _identity(email: str) -> SeedIdentity:
    return SeedIdentity(
        email=email,
        password="a-secure-seed-password",
        first_name="Seed",
        last_name="User",
    )


def test_seed_config_requires_unique_emails() -> None:
    with pytest.raises(ValidationError, match="must be unique"):
        UserSeedConfig(
            organization_name="Demo organization",
            super_admin=_identity("same@example.com"),
            org_admin=_identity("same@example.com"),
            user=_identity("user@example.com"),
        )


def test_seed_identity_rejects_short_password() -> None:
    with pytest.raises(ValidationError):
        SeedIdentity(
            email="user@example.com",
            password="short",
            first_name="Seed",
            last_name="User",
        )
