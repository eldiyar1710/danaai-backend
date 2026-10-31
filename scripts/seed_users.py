import argparse
import asyncio
import os
import sys
from dataclasses import dataclass
from getpass import getpass
from pathlib import Path

# Allow both `python -m scripts.seed_users` and direct script execution.
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic import BaseModel, EmailStr, Field, ValidationError, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.models  # noqa: F401  # Register every table referenced by ORM foreign keys.
from app.core.config import get_settings
from app.core.database import create_engine, create_session_factory
from app.core.security import hash_password
from app.modules.organizations.models import Organization
from app.modules.users.models import User, UserRole


class SeedIdentity(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=256)
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)


class UserSeedConfig(BaseModel):
    organization_name: str = Field(min_length=2, max_length=255)
    organization_description: str | None = None
    super_admin: SeedIdentity
    org_admin: SeedIdentity
    user: SeedIdentity

    @model_validator(mode="after")
    def unique_emails(self) -> "UserSeedConfig":
        emails = {
            str(self.super_admin.email).lower(),
            str(self.org_admin.email).lower(),
            str(self.user.email).lower(),
        }
        if len(emails) != 3:
            raise ValueError("Seed user email addresses must be unique")
        return self


@dataclass(frozen=True)
class SeedResult:
    organization_created: bool
    user_statuses: dict[str, str]


async def _ensure_user(
    session: AsyncSession,
    identity: SeedIdentity,
    *,
    role: UserRole,
    organization: Organization | None,
    reset_password: bool,
) -> str:
    email = str(identity.email).lower()
    existing = await session.scalar(select(User).where(User.email == email))
    expected_organization_id = organization.id if organization is not None else None
    if existing is not None:
        if existing.role != role or existing.organization_id != expected_organization_id:
            raise RuntimeError(
                f"Existing user {email} has a different role or organization; "
                "refusing to modify tenant membership"
            )
        if reset_password:
            existing.hashed_password = hash_password(identity.password)
            return "password_reset"
        return "existing"

    session.add(
        User(
            organization_id=expected_organization_id,
            email=email,
            hashed_password=hash_password(identity.password),
            first_name=identity.first_name.strip(),
            last_name=identity.last_name.strip(),
            role=role,
            is_active=True,
        )
    )
    return "created"


async def seed_users(config: UserSeedConfig, *, reset_passwords: bool = False) -> SeedResult:
    settings = get_settings()
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    try:
        async with factory() as session, session.begin():
            organization = await session.scalar(
                select(Organization).where(Organization.name == config.organization_name.strip())
            )
            organization_created = organization is None
            if organization is None:
                organization = Organization(
                    name=config.organization_name.strip(),
                    description=config.organization_description,
                    is_active=True,
                )
                session.add(organization)
                await session.flush()

            statuses = {
                "super_admin": await _ensure_user(
                    session,
                    config.super_admin,
                    role=UserRole.SUPER_ADMIN,
                    organization=None,
                    reset_password=reset_passwords,
                ),
                "org_admin": await _ensure_user(
                    session,
                    config.org_admin,
                    role=UserRole.ORG_ADMIN,
                    organization=organization,
                    reset_password=reset_passwords,
                ),
                "user": await _ensure_user(
                    session,
                    config.user,
                    role=UserRole.USER,
                    organization=organization,
                    reset_password=reset_passwords,
                ),
            }
        return SeedResult(
            organization_created=organization_created,
            user_statuses=statuses,
        )
    finally:
        await engine.dispose()


def _password(environment_name: str, prompt: str) -> str:
    configured = os.getenv(environment_name)
    if configured:
        return configured
    if not sys.stdin.isatty():
        raise SystemExit(
            f"{environment_name} is required when seed_users.py runs non-interactively"
        )
    return getpass(prompt)


def _identity(
    prefix: str,
    default_email: str,
    default_first_name: str,
    default_last_name: str,
) -> SeedIdentity:
    return SeedIdentity(
        email=os.getenv(f"SEED_{prefix}_EMAIL", default_email),
        password=_password(f"SEED_{prefix}_PASSWORD", f"{prefix.title()} password: "),
        first_name=os.getenv(f"SEED_{prefix}_FIRST_NAME", default_first_name),
        last_name=os.getenv(f"SEED_{prefix}_LAST_NAME", default_last_name),
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Idempotently seed a development organization and its users"
    )
    parser.add_argument(
        "--organization-name",
        default=os.getenv("SEED_ORGANIZATION_NAME", "Semyzbay Demo"),
    )
    parser.add_argument(
        "--organization-description",
        default=os.getenv("SEED_ORGANIZATION_DESCRIPTION", "Local development organization"),
    )
    parser.add_argument(
        "--reset-passwords",
        action="store_true",
        help="Replace passwords when seed users already exist",
    )
    args = parser.parse_args()
    try:
        config = UserSeedConfig(
            organization_name=args.organization_name,
            organization_description=args.organization_description,
            super_admin=_identity(
                "SUPER_ADMIN", "superadmin@semyzbay.kz", "System", "Administrator"
            ),
            org_admin=_identity(
                "ORG_ADMIN", "orgadmin@semyzbay.kz", "Organization", "Administrator"
            ),
            user=_identity("USER", "user@semyzbay.kz", "Demo", "User"),
        )
    except ValidationError as exc:
        raise SystemExit(str(exc)) from exc

    result = asyncio.run(seed_users(config, reset_passwords=args.reset_passwords))
    organization_status = "created" if result.organization_created else "existing"
    print(f"Organization: {config.organization_name} ({organization_status})")
    print(f"Super admin: {config.super_admin.email} ({result.user_statuses['super_admin']})")
    print(f"Org admin: {config.org_admin.email} ({result.user_statuses['org_admin']})")
    print(f"User: {config.user.email} ({result.user_statuses['user']})")


if __name__ == "__main__":
    main()
