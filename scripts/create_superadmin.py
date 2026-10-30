import argparse
import asyncio
import sys
from getpass import getpass
from pathlib import Path

# Allow both `python -m scripts.create_superadmin` and direct script execution.
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy.exc import IntegrityError

import app.models  # noqa: F401  # Register every table referenced by ORM foreign keys.
from app.core.config import get_settings
from app.core.database import create_engine, create_session_factory
from app.core.security import hash_password
from app.modules.users.models import User, UserRole


async def create_superadmin(email: str, password: str, first_name: str, last_name: str) -> None:
    settings = get_settings()
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            session.add(
                User(
                    organization_id=None,
                    email=email.lower(),
                    hashed_password=hash_password(password),
                    first_name=first_name,
                    last_name=last_name,
                    role=UserRole.SUPER_ADMIN,
                    is_active=True,
                )
            )
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                raise SystemExit("A user with this email already exists") from exc
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Create the initial Semyzbay super administrator")
    parser.add_argument("--email", required=True)
    parser.add_argument("--first-name", required=True)
    parser.add_argument("--last-name", required=True)
    args = parser.parse_args()
    try:
        email = str(TypeAdapter(EmailStr).validate_python(args.email))
    except ValidationError as exc:
        raise SystemExit("A valid email address is required") from exc
    password = getpass("Password (at least 12 characters): ")
    if len(password) < 12:
        raise SystemExit("Password must contain at least 12 characters")
    asyncio.run(create_superadmin(email, password, args.first_name, args.last_name))


if __name__ == "__main__":
    main()
