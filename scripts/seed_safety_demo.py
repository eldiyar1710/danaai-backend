import argparse
import asyncio
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from getpass import getpass
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.models  # noqa: F401
from app.core.config import get_settings
from app.core.database import create_engine, create_session_factory
from app.core.security import hash_password
from app.modules.organizations.models import Organization
from app.modules.safety.models import (
    EmployeeSafetyProfile,
    EmployeeSafetyStage,
    EmployeeWorkScope,
    SafetyStageStatus,
)
from app.modules.users.models import User, UserRole


@dataclass(frozen=True)
class ScopeSeed:
    code: str
    title: str


@dataclass(frozen=True)
class StageSeed:
    order: int
    code: str
    title: str
    status: SafetyStageStatus
    score: int | None
    activity_code: str | None = None
    notes: str | None = None


@dataclass(frozen=True)
class EmployeeSeed:
    email: str
    first_name: str
    last_name: str
    personnel_number: str
    position_code: str
    position_title: str
    hire_year: int
    scopes: tuple[ScopeSeed, ...]
    stages: tuple[StageSeed, ...]


EMPLOYEES = (
    EmployeeSeed(
        email="bagzhan.tolepbergen@danaai.kz",
        first_name="Багжан",
        last_name="Толепберген",
        personnel_number="DEMO-EL-001",
        position_code="electrician",
        position_title="Электрик",
        hire_year=2025,
        scopes=(
            ScopeSeed("electrical_work", "Электромонтажные работы"),
            ScopeSeed("work_at_height", "Работы на высоте"),
        ),
        stages=(
            StageSeed(1, "introductory", "Вводный инструктаж", SafetyStageStatus.PASSED, 92),
            StageSeed(
                2,
                "profession",
                "Безопасность работ электрика",
                SafetyStageStatus.PASSED,
                90,
            ),
            StageSeed(
                3,
                "ppe_first_aid",
                "СИЗ и первая помощь",
                SafetyStageStatus.PASSED,
                88,
            ),
            StageSeed(
                4,
                "special_hazards",
                "Безопасность работ на высоте",
                SafetyStageStatus.FAILED,
                65,
                "work_at_height",
                "Работа на высоте запрещена до успешной пересдачи",
            ),
            StageSeed(
                5, "final_assessment", "Итоговая проверка", SafetyStageStatus.PASSED, 88
            ),
        ),
    ),
    EmployeeSeed(
        email="abai.kozhdan@danaai.kz",
        first_name="Абай",
        last_name="Кождан",
        personnel_number="DEMO-WD-002",
        position_code="welder",
        position_title="Сварщик",
        hire_year=2022,
        scopes=(ScopeSeed("welding_work", "Сварочные работы"),),
        stages=(
            StageSeed(1, "introductory", "Вводный инструктаж", SafetyStageStatus.PASSED, 94),
            StageSeed(
                2,
                "profession",
                "Безопасность газоэлектросварочных работ",
                SafetyStageStatus.PASSED,
                91,
            ),
            StageSeed(
                3,
                "ppe_first_aid",
                "СИЗ и первая помощь",
                SafetyStageStatus.PASSED,
                90,
            ),
            StageSeed(
                4,
                "special_hazards",
                "Пожарная безопасность и баллоны",
                SafetyStageStatus.PASSED,
                89,
                "welding_work",
            ),
            StageSeed(
                5, "final_assessment", "Итоговая проверка", SafetyStageStatus.PASSED, 92
            ),
        ),
    ),
    EmployeeSeed(
        email="nurtas.bakbergenov@danaai.kz",
        first_name="Нуртас",
        last_name="Бакбергенов",
        personnel_number="DEMO-DR-003",
        position_code="driver",
        position_title="Водитель",
        hire_year=2026,
        scopes=(ScopeSeed("driving", "Управление служебным автомобилем"),),
        stages=(
            StageSeed(1, "introductory", "Вводный инструктаж", SafetyStageStatus.NOT_STARTED, None),
            StageSeed(
                2,
                "profession",
                "Безопасность труда водителя",
                SafetyStageStatus.NOT_STARTED,
                None,
            ),
            StageSeed(
                3,
                "ppe_first_aid",
                "СИЗ и первая помощь",
                SafetyStageStatus.NOT_STARTED,
                None,
            ),
            StageSeed(
                4,
                "special_hazards",
                "Предрейсовый контроль и безопасность перевозок",
                SafetyStageStatus.NOT_STARTED,
                None,
                "driving",
            ),
            StageSeed(
                5,
                "final_assessment",
                "Итоговая проверка",
                SafetyStageStatus.NOT_STARTED,
                None,
            ),
        ),
    ),
)


def _password() -> str:
    configured = os.getenv("SEED_SAFETY_EMPLOYEE_PASSWORD")
    if configured:
        if len(configured) < 12:
            raise SystemExit("SEED_SAFETY_EMPLOYEE_PASSWORD must contain at least 12 characters")
        return configured
    if not sys.stdin.isatty():
        raise SystemExit("SEED_SAFETY_EMPLOYEE_PASSWORD is required in non-interactive mode")
    value = getpass("Password for the three demo employees: ")
    if len(value) < 12:
        raise SystemExit("Password must contain at least 12 characters")
    return value


async def _ensure_user(
    session: AsyncSession,
    employee: EmployeeSeed,
    organization: Organization,
    password: str,
    *,
    reset_password: bool,
) -> User:
    user = await session.scalar(select(User).where(User.email == employee.email))
    if user is not None:
        if user.organization_id != organization.id or user.role != UserRole.USER:
            raise RuntimeError(f"Existing user {employee.email} belongs to another tenant or role")
        if reset_password:
            user.hashed_password = hash_password(password)
        return user
    user = User(
        organization_id=organization.id,
        email=employee.email,
        hashed_password=hash_password(password),
        first_name=employee.first_name,
        last_name=employee.last_name,
        role=UserRole.USER,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


async def _ensure_profile(
    session: AsyncSession,
    employee: EmployeeSeed,
    organization: Organization,
    user: User,
    *,
    reset: bool,
) -> str:
    profile = await session.scalar(
        select(EmployeeSafetyProfile).where(EmployeeSafetyProfile.user_id == user.id)
    )
    if profile is not None and not reset:
        return "existing"
    if profile is None:
        profile = EmployeeSafetyProfile(
            organization_id=organization.id,
            user_id=user.id,
            personnel_number=employee.personnel_number,
            position_code=employee.position_code,
            position_title=employee.position_title,
            hire_year=employee.hire_year,
        )
        session.add(profile)
        await session.flush()
    else:
        profile.personnel_number = employee.personnel_number
        profile.position_code = employee.position_code
        profile.position_title = employee.position_title
        profile.hire_year = employee.hire_year
        for stage in await session.scalars(
            select(EmployeeSafetyStage).where(EmployeeSafetyStage.profile_id == profile.id)
        ):
            await session.delete(stage)
        for scope in await session.scalars(
            select(EmployeeWorkScope).where(EmployeeWorkScope.profile_id == profile.id)
        ):
            await session.delete(scope)
        await session.flush()

    session.add_all(
        EmployeeWorkScope(profile_id=profile.id, code=scope.code, title=scope.title)
        for scope in employee.scopes
    )
    await session.flush()
    now = datetime.now(UTC)
    session.add_all(
        EmployeeSafetyStage(
            profile_id=profile.id,
            stage_order=stage.order,
            code=stage.code,
            title=stage.title,
            status=stage.status,
            score=stage.score,
            passing_score=80,
            activity_code=stage.activity_code,
            passed_at=now if stage.status == SafetyStageStatus.PASSED else None,
            expires_at=None,
            notes=stage.notes,
        )
        for stage in employee.stages
    )
    return "reset" if reset else "created"


async def seed(
    organization_name: str,
    password: str,
    *,
    reset: bool,
    reset_passwords: bool = False,
) -> dict[str, str]:
    settings = get_settings()
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    try:
        async with factory() as session, session.begin():
            organization = await session.scalar(
                select(Organization).where(Organization.name == organization_name)
            )
            if organization is None:
                raise RuntimeError(
                    f"Organization {organization_name!r} does not exist; run seed_users.py first"
                )
            results: dict[str, str] = {}
            for employee in EMPLOYEES:
                user = await _ensure_user(
                    session,
                    employee,
                    organization,
                    password,
                    reset_password=reset_passwords,
                )
                results[employee.email] = await _ensure_profile(
                    session, employee, organization, user, reset=reset
                )
            return results
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed three demo employees and five safety stages")
    parser.add_argument(
        "--organization-name",
        default=os.getenv("SEED_ORGANIZATION_NAME", "Semyzbay Demo"),
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Restore the demo safety statuses without changing employee passwords",
    )
    parser.add_argument(
        "--reset-passwords",
        action="store_true",
        help="Set the configured common password for all three demo employees",
    )
    args = parser.parse_args()
    results = asyncio.run(
        seed(
            args.organization_name,
            _password(),
            reset=args.reset,
            reset_passwords=args.reset_passwords,
        )
    )
    for employee in EMPLOYEES:
        print(f"{employee.last_name} {employee.first_name}: {results[employee.email]}")


if __name__ == "__main__":
    main()
