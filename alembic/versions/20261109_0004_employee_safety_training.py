"""Add employee safety training and granular work clearances.

Revision ID: 20261109_0004
Revises: 20261031_0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20261109_0004"
down_revision: str | None = "20261031_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

safety_stage_status = postgresql.ENUM(
    "NOT_STARTED",
    "IN_PROGRESS",
    "PASSED",
    "FAILED",
    name="safety_stage_status",
    create_type=False,
)


def _timestamps() -> list[sa.Column[object]]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    safety_stage_status.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "employee_safety_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("personnel_number", sa.String(50), nullable=False),
        sa.Column("position_code", sa.String(100), nullable=False),
        sa.Column("position_title", sa.String(255), nullable=False),
        sa.Column("hire_year", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("user_id"),
        sa.UniqueConstraint("id", "organization_id", name="uq_safety_profiles_id_organization"),
        sa.CheckConstraint(
            "hire_year >= 1900 AND hire_year <= 2200", name="ck_safety_profiles_valid_hire_year"
        ),
    )
    op.create_index(
        "ix_safety_profiles_organization_position",
        "employee_safety_profiles",
        ["organization_id", "position_code"],
    )

    op.create_table(
        "employee_work_scopes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "profile_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("employee_safety_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.UniqueConstraint("profile_id", "code"),
    )
    op.create_index(
        "ix_employee_work_scopes_profile", "employee_work_scopes", ["profile_id"]
    )

    op.create_table(
        "employee_safety_stages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "profile_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("employee_safety_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("stage_order", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("status", safety_stage_status, nullable=False),
        sa.Column("score", sa.Integer()),
        sa.Column("passing_score", sa.Integer(), server_default="80", nullable=False),
        sa.Column("activity_code", sa.String(100)),
        sa.Column("passed_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("notes", sa.Text()),
        *_timestamps(),
        sa.UniqueConstraint(
            "profile_id", "stage_order", name="uq_employee_safety_stages_profile_order"
        ),
        sa.UniqueConstraint(
            "profile_id", "code", name="uq_employee_safety_stages_profile_code"
        ),
        sa.ForeignKeyConstraint(
            ["profile_id", "activity_code"],
            ["employee_work_scopes.profile_id", "employee_work_scopes.code"],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "stage_order >= 1 AND stage_order <= 5", name="ck_safety_stages_stage_order_range"
        ),
        sa.CheckConstraint(
            "passing_score >= 0 AND passing_score <= 100",
            name="ck_safety_stages_passing_score_range",
        ),
        sa.CheckConstraint(
            "score IS NULL OR (score >= 0 AND score <= 100)",
            name="ck_safety_stages_score_range",
        ),
    )
    op.create_index(
        "ix_employee_safety_stages_profile_status",
        "employee_safety_stages",
        ["profile_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_employee_safety_stages_profile_status", table_name="employee_safety_stages"
    )
    op.drop_table("employee_safety_stages")
    op.drop_index("ix_employee_work_scopes_profile", table_name="employee_work_scopes")
    op.drop_table("employee_work_scopes")
    op.drop_index(
        "ix_safety_profiles_organization_position", table_name="employee_safety_profiles"
    )
    op.drop_table("employee_safety_profiles")
    safety_stage_status.drop(op.get_bind(), checkfirst=True)
