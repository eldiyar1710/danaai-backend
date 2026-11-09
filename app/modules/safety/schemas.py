from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from app.modules.safety.models import SafetyStageStatus


class SafetyStageRead(BaseModel):
    id: UUID
    order: int
    code: str
    title: str
    status: SafetyStageStatus | str
    score: int | None
    passing_score: int
    activity_code: str | None
    passed_at: datetime | None
    expires_at: datetime | None
    notes: str | None


class WorkScopeRead(BaseModel):
    code: str
    title: str
    status: str
    blocking_stage_codes: list[str]


class EmployeeSafetyRead(BaseModel):
    user_id: UUID
    organization_id: UUID
    email: str
    first_name: str
    last_name: str
    personnel_number: str
    position_code: str
    position_title: str
    hire_year: int
    completed_stages: int
    total_stages: int
    progress_percent: int
    overall_status: str
    has_any_work_access: bool
    stages: list[SafetyStageRead]
    work_scopes: list[WorkScopeRead]


class SafetyStageUpdate(BaseModel):
    status: SafetyStageStatus
    score: int | None = Field(default=None, ge=0, le=100)
    expires_at: datetime | None = None
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("expires_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.utcoffset() is None:
            raise ValueError("expires_at must include a timezone")
        return value

    @model_validator(mode="after")
    def validate_passed_score(self) -> "SafetyStageUpdate":
        if self.status == SafetyStageStatus.PASSED and self.score is None:
            raise ValueError("score is required when a stage is passed")
        return self
