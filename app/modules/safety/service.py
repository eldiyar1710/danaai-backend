from collections.abc import Mapping
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException

from app.modules.safety.models import (
    EmployeeSafetyProfile,
    EmployeeSafetyStage,
    EmployeeWorkScope,
    SafetyStageStatus,
)
from app.modules.safety.repository import SafetyRepository
from app.modules.safety.schemas import (
    EmployeeSafetyRead,
    SafetyStageRead,
    SafetyStageUpdate,
    WorkScopeRead,
)
from app.modules.users.models import User, UserRole


class SafetyService:
    def __init__(self, repository: SafetyRepository) -> None:
        self.repository = repository

    async def list_employees(self, actor: User) -> list[EmployeeSafetyRead]:
        if actor.role not in {UserRole.SUPER_ADMIN, UserRole.ORG_ADMIN}:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        organization_id = None if actor.role == UserRole.SUPER_ADMIN else actor.organization_id
        profiles = await self.repository.list_profiles(organization_id)
        return [await self._read(profile) for profile in profiles]

    async def get(self, actor: User, user_id: UUID) -> EmployeeSafetyRead:
        profile = await self._profile(user_id)
        self._authorize_read(actor, profile)
        return await self._read(profile)

    async def update_stage(
        self, actor: User, user_id: UUID, stage_code: str, data: SafetyStageUpdate
    ) -> EmployeeSafetyRead:
        profile = await self._profile(user_id)
        self._authorize_admin(actor, profile)
        stage = await self.repository.get_stage(profile.id, stage_code)
        if stage is None:
            raise HTTPException(status_code=404, detail="Safety stage not found")
        if data.status == SafetyStageStatus.PASSED:
            if data.score is None or data.score < stage.passing_score:
                raise HTTPException(
                    status_code=422,
                    detail=f"A passing score of at least {stage.passing_score} is required",
                )
            if data.expires_at is not None and data.expires_at <= datetime.now(UTC):
                raise HTTPException(status_code=422, detail="expires_at must be in the future")
            stage.passed_at = datetime.now(UTC)
        else:
            stage.passed_at = None
        stage.status = data.status
        stage.score = data.score
        stage.expires_at = data.expires_at
        stage.notes = data.notes
        await self.repository.session.commit()
        await self.repository.session.refresh(stage)
        return await self._read(profile)

    async def _profile(self, user_id: UUID) -> EmployeeSafetyProfile:
        profile = await self.repository.get_profile_by_user(user_id)
        if profile is None:
            raise HTTPException(status_code=404, detail="Employee safety profile not found")
        return profile

    @staticmethod
    def _authorize_read(actor: User, profile: EmployeeSafetyProfile) -> None:
        if actor.id == profile.user_id:
            return
        SafetyService._authorize_admin(actor, profile)

    @staticmethod
    def _authorize_admin(actor: User, profile: EmployeeSafetyProfile) -> None:
        if actor.role == UserRole.SUPER_ADMIN:
            return
        if actor.role == UserRole.ORG_ADMIN and actor.organization_id == profile.organization_id:
            return
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    async def _read(self, profile: EmployeeSafetyProfile) -> EmployeeSafetyRead:
        user = await self.repository.get_user(profile.user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="Employee user not found")
        stages = await self.repository.list_stages(profile.id)
        scopes = await self.repository.list_scopes(profile.id)
        now = datetime.now(UTC)
        effective = {stage.code: self._effective_status(stage, now) for stage in stages}
        scope_reads = [self._scope_read(scope, stages, effective) for scope in scopes]
        passed = sum(status == SafetyStageStatus.PASSED for status in effective.values())
        allowed = sum(scope.status == "allowed" for scope in scope_reads)
        if allowed == len(scope_reads) and scope_reads:
            overall_status = "allowed"
        elif allowed:
            overall_status = "partial"
        else:
            overall_status = "blocked"
        total = len(stages)
        return EmployeeSafetyRead(
            user_id=user.id,
            organization_id=profile.organization_id,
            email=user.email,
            first_name=user.first_name,
            last_name=user.last_name,
            personnel_number=profile.personnel_number,
            position_code=profile.position_code,
            position_title=profile.position_title,
            hire_year=profile.hire_year,
            completed_stages=passed,
            total_stages=total,
            progress_percent=round(passed * 100 / total) if total else 0,
            overall_status=overall_status,
            has_any_work_access=allowed > 0,
            stages=[
                SafetyStageRead(
                    id=stage.id,
                    order=stage.stage_order,
                    code=stage.code,
                    title=stage.title,
                    status=effective[stage.code],
                    score=stage.score,
                    passing_score=stage.passing_score,
                    activity_code=stage.activity_code,
                    passed_at=stage.passed_at,
                    expires_at=stage.expires_at,
                    notes=stage.notes,
                )
                for stage in stages
            ],
            work_scopes=scope_reads,
        )

    @staticmethod
    def _effective_status(stage: EmployeeSafetyStage, now: datetime) -> SafetyStageStatus | str:
        if (
            stage.status == SafetyStageStatus.PASSED
            and stage.expires_at is not None
            and stage.expires_at <= now
        ):
            return "expired"
        return stage.status

    @staticmethod
    def _scope_read(
        scope: EmployeeWorkScope,
        stages: list[EmployeeSafetyStage],
        effective: Mapping[str, SafetyStageStatus | str],
    ) -> WorkScopeRead:
        applicable = [
            stage
            for stage in stages
            if stage.activity_code is None or stage.activity_code == scope.code
        ]
        blockers = [
            stage.code
            for stage in applicable
            if effective[stage.code] != SafetyStageStatus.PASSED
        ]
        return WorkScopeRead(
            code=scope.code,
            title=scope.title,
            status="allowed" if not blockers else "blocked",
            blocking_stage_codes=blockers,
        )
