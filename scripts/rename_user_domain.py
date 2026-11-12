"""Move user logins to another email domain and optionally set one common password.

Run inside the API container:

    docker compose exec semyzbay-api python scripts/rename_user_domain.py --dry-run
    docker compose exec semyzbay-api python scripts/rename_user_domain.py --reset-passwords

By default every user whose email ends with ``@semyzbay.kz`` is renamed to the same
local part at ``@danaai.kz``. With ``--reset-passwords`` every *active* user (renamed or
not) gets the password typed at the prompt or taken from ``NEW_USER_PASSWORD``.
Refresh tokens are not touched; existing sessions keep working until they expire.
"""

import argparse
import asyncio
import os
import sys
from getpass import getpass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

import app.models  # noqa: F401
from app.core.config import get_settings
from app.core.database import create_engine, create_session_factory
from app.core.security import hash_password
from app.modules.users.models import User

MIN_PASSWORD_LENGTH = 12


def _password() -> str:
    value = os.getenv("NEW_USER_PASSWORD")
    if value is None:
        if not sys.stdin.isatty():
            raise SystemExit("NEW_USER_PASSWORD is required in non-interactive mode")
        value = getpass("New password for all active users: ")
        if value != getpass("Repeat the password: "):
            raise SystemExit("Passwords do not match")
    if len(value) < MIN_PASSWORD_LENGTH:
        raise SystemExit(f"Password must contain at least {MIN_PASSWORD_LENGTH} characters")
    return value


def renamed(email: str, old: str, new: str) -> str | None:
    local, _, domain = email.rpartition("@")
    if local and domain.lower() == old.lower():
        return f"{local}@{new.lower()}"
    return None


async def run(
    old: str, new: str, password: str | None, *, reset_passwords: bool, dry_run: bool
) -> None:
    engine = create_engine(get_settings())
    factory = create_session_factory(engine)
    try:
        async with factory() as session, session.begin():
            users = list(await session.scalars(select(User).order_by(User.email)))
            taken = {user.email.lower() for user in users}
            for user in users:
                target = renamed(user.email, old, new)
                if target and target.lower() in taken:
                    raise SystemExit(f"Cannot rename {user.email}: {target} already exists")
            for user in users:
                target = renamed(user.email, old, new)
                reset = reset_passwords and user.is_active
                changes = []
                if target:
                    changes.append(f"{user.email} -> {target}")
                    user.email = target
                if reset:
                    changes.append("password reset")
                    if password is not None:
                        user.hashed_password = hash_password(password)
                state = "active" if user.is_active else "inactive"
                print(f"{user.email:<48} {state:<8} {'; '.join(changes) or 'unchanged'}")
            if dry_run:
                await session.rollback()
                print("Dry run: nothing was saved.")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--from-domain", default="semyzbay.kz")
    parser.add_argument("--to-domain", default="danaai.kz")
    parser.add_argument("--reset-passwords", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Show changes without saving")
    args = parser.parse_args()
    password = _password() if args.reset_passwords and not args.dry_run else None
    asyncio.run(
        run(
            args.from_domain,
            args.to_domain,
            password,
            reset_passwords=args.reset_passwords,
            dry_run=args.dry_run,
        )
    )


if __name__ == "__main__":
    main()
