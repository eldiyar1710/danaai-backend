import enum
from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, TimestampMixin, UUIDPrimaryKeyMixin


class SafetyStageStatus(enum.StrEnum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    PASSED = "passed"
    FAILED = "failed"


class EmployeeSafetyProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "employee_safety_profiles"
    __table_args__ = (
        UniqueConstraint("user_id"),
        UniqueConstraint("id", "organization_id", name="uq_safety_profiles_id_organization"),
        Index("ix_safety_profiles_organization_position", "organization_id", "position_code"),
        CheckConstraint("hire_year >= 1900 AND hire_year <= 2200", name="valid_hire_year"),
    )

    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE")
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    personnel_number: Mapped[str] = mapped_column(String(50))
    position_code: Mapped[str] = mapped_column(String(100))
    position_title: Mapped[str] = mapped_column(String(255))
    hire_year: Mapped[int] = mapped_column(Integer)


class EmployeeWorkScope(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "employee_work_scopes"
    __table_args__ = (
        UniqueConstraint("profile_id", "code"),
        Index("ix_employee_work_scopes_profile", "profile_id"),
    )

    profile_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("employee_safety_profiles.id", ondelete="CASCADE")
    )
    code: Mapped[str] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(String(255))


class EmployeeSafetyStage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "employee_safety_stages"
    __table_args__ = (
        UniqueConstraint(
            "profile_id", "stage_order", name="uq_employee_safety_stages_profile_order"
        ),
        UniqueConstraint("profile_id", "code", name="uq_employee_safety_stages_profile_code"),
        ForeignKeyConstraint(
            ["profile_id", "activity_code"],
            ["employee_work_scopes.profile_id", "employee_work_scopes.code"],
            ondelete="CASCADE",
        ),
        Index("ix_employee_safety_stages_profile_status", "profile_id", "status"),
        CheckConstraint("stage_order >= 1 AND stage_order <= 5", name="stage_order_range"),
        CheckConstraint("passing_score >= 0 AND passing_score <= 100", name="passing_score_range"),
        CheckConstraint("score IS NULL OR (score >= 0 AND score <= 100)", name="score_range"),
    )

    profile_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("employee_safety_profiles.id", ondelete="CASCADE")
    )
    stage_order: Mapped[int] = mapped_column(Integer)
    code: Mapped[str] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(String(255))
    status: Mapped[SafetyStageStatus] = mapped_column(
        Enum(SafetyStageStatus, name="safety_stage_status"),
        default=SafetyStageStatus.NOT_STARTED,
    )
    score: Mapped[int | None] = mapped_column(Integer)
    passing_score: Mapped[int] = mapped_column(Integer, default=80, server_default="80")
    activity_code: Mapped[str | None] = mapped_column(String(100))
    passed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)
