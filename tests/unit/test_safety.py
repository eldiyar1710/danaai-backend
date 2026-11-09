from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.safety.models import EmployeeSafetyStage, EmployeeWorkScope, SafetyStageStatus
from app.modules.safety.schemas import SafetyStageUpdate
from app.modules.safety.service import SafetyService
from scripts.seed_safety_demo import EMPLOYEES


def _stage(
    profile_id: object,
    code: str,
    status: SafetyStageStatus,
    activity_code: str | None = None,
) -> EmployeeSafetyStage:
    return EmployeeSafetyStage(
        profile_id=profile_id,
        stage_order=1,
        code=code,
        title=code,
        status=status,
        score=90 if status == SafetyStageStatus.PASSED else 50,
        passing_score=80,
        activity_code=activity_code,
        passed_at=None,
        expires_at=None,
        notes=None,
    )


def test_activity_specific_failure_does_not_block_other_work() -> None:
    profile_id = uuid4()
    electrical = EmployeeWorkScope(
        profile_id=profile_id, code="electrical_work", title="Electrical work"
    )
    height = EmployeeWorkScope(
        profile_id=profile_id, code="work_at_height", title="Work at height"
    )
    stages = [
        _stage(profile_id, "introductory", SafetyStageStatus.PASSED),
        _stage(
            profile_id,
            "special_hazards",
            SafetyStageStatus.FAILED,
            activity_code="work_at_height",
        ),
    ]
    effective = {stage.code: stage.status for stage in stages}

    electrical_status = SafetyService._scope_read(electrical, stages, effective)
    height_status = SafetyService._scope_read(height, stages, effective)

    assert electrical_status.status == "allowed"
    assert electrical_status.blocking_stage_codes == []
    assert height_status.status == "blocked"
    assert height_status.blocking_stage_codes == ["special_hazards"]


def test_expired_pass_is_effectively_expired() -> None:
    stage = _stage(uuid4(), "introductory", SafetyStageStatus.PASSED)
    stage.expires_at = datetime.now(UTC) - timedelta(seconds=1)

    assert SafetyService._effective_status(stage, datetime.now(UTC)) == "expired"


def test_passed_stage_requires_score() -> None:
    with pytest.raises(ValidationError, match="score is required"):
        SafetyStageUpdate(status=SafetyStageStatus.PASSED)


def test_stage_expiration_requires_timezone() -> None:
    with pytest.raises(ValidationError, match="must include a timezone"):
        SafetyStageUpdate(
            status=SafetyStageStatus.PASSED,
            score=90,
            expires_at=datetime(2027, 1, 1),
        )


def test_demo_seed_contains_three_employees_with_five_stages() -> None:
    assert len(EMPLOYEES) == 3
    assert all(len(employee.stages) == 5 for employee in EMPLOYEES)
    assert {employee.position_code for employee in EMPLOYEES} == {
        "electrician",
        "welder",
        "driver",
    }


def test_demo_electrician_is_blocked_only_from_height() -> None:
    employee = next(item for item in EMPLOYEES if item.position_code == "electrician")
    special = next(stage for stage in employee.stages if stage.code == "special_hazards")

    assert special.status == SafetyStageStatus.FAILED
    assert special.activity_code == "work_at_height"
