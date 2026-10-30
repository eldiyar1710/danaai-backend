"""Initial tenant-aware schema.

Revision ID: 20261029_0001
Revises: None
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20261029_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

user_role = sa.Enum("SUPER_ADMIN", "ORG_ADMIN", "USER", name="user_role")
document_status = sa.Enum(
    "UPLOADED", "PROCESSING", "READY", "FAILED", "ARCHIVED", name="document_status"
)
approval_status = sa.Enum("PENDING", "APPROVED", "REJECTED", "ARCHIVED", name="approval_status")
processing_status = sa.Enum("PENDING", "RUNNING", "SUCCEEDED", "FAILED", name="processing_status")
job_status = sa.Enum("PENDING", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED", name="job_status")
message_role = sa.Enum("USER", "ASSISTANT", "SYSTEM", name="message_role")
generation_status = sa.Enum(
    "PENDING", "ANSWERED", "INSUFFICIENT_CONTEXT", "FAILED", name="generation_status"
)


def timestamps() -> list[sa.Column[object]]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        *timestamps(),
        sa.UniqueConstraint("name"),
    )
    op.create_index("ix_organizations_name", "organizations", ["name"])
    op.create_index("ix_organizations_is_active", "organizations", ["is_active"])

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
        ),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("hashed_password", sa.String(512), nullable=False),
        sa.Column("first_name", sa.String(100), nullable=False),
        sa.Column("last_name", sa.String(100), nullable=False),
        sa.Column("role", user_role, nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        *timestamps(),
        sa.UniqueConstraint("email"),
        sa.CheckConstraint(
            "(role = 'SUPER_ADMIN' AND organization_id IS NULL) OR "
            "(role <> 'SUPER_ADMIN' AND organization_id IS NOT NULL)",
            name="ck_users_role_organization",
        ),
    )
    op.create_index("ix_users_organization_role", "users", ["organization_id", "role"])
    op.create_index("ix_users_email", "users", ["email"])

    op.create_table(
        "refresh_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(128), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_refresh_sessions_user_expires", "refresh_sessions", ["user_id", "expires_at"]
    )

    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "uploaded_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("original_filename", sa.String(500), nullable=False),
        sa.Column("minio_path", sa.String(1024), nullable=False, unique=True),
        sa.Column("mime_type", sa.String(255), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("language", sa.String(8), nullable=False),
        sa.Column("status", document_status, nullable=False),
        sa.Column("approval_status", approval_status, nullable=False),
        sa.Column("active_version_id", postgresql.UUID(as_uuid=True)),
        *timestamps(),
        sa.UniqueConstraint("organization_id", "id", name="uq_documents_organization_id_id"),
        sa.CheckConstraint("size_bytes > 0", name="ck_documents_positive_size"),
    )
    op.create_index(
        "ix_documents_tenant_status", "documents", ["organization_id", "approval_status", "status"]
    )

    op.create_table(
        "document_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("minio_path", sa.String(1024), nullable=False, unique=True),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True)),
        sa.Column("effective_until", sa.DateTime(timezone=True)),
        sa.Column(
            "approved_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("processing_status", processing_status, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("document_id", "version_number"),
        sa.UniqueConstraint("document_id", "id", name="uq_document_versions_document_id_id"),
        sa.CheckConstraint("version_number > 0", name="ck_document_versions_positive_version"),
        sa.CheckConstraint(
            "effective_until IS NULL OR effective_from IS NULL OR effective_until > effective_from",
            name="ck_document_versions_effective_range",
        ),
    )
    op.create_foreign_key(
        "fk_documents_active_version_id_document_versions",
        "documents",
        "document_versions",
        ["id", "active_version_id"],
        ["document_id", "id"],
        ondelete="RESTRICT",
    )

    op.create_table(
        "document_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("qdrant_point_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("page_number", sa.Integer()),
        sa.Column("section_title", sa.String(500)),
        sa.Column("section_number", sa.String(100)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "document_id"],
            ["documents.organization_id", "documents.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_id", "document_version_id"],
            ["document_versions.document_id", "document_versions.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("document_version_id", "chunk_index"),
        sa.CheckConstraint("chunk_index >= 0", name="ck_document_chunks_nonnegative_chunk_index"),
    )
    op.create_index(
        "ix_document_chunks_tenant_document", "document_chunks", ["organization_id", "document_id"]
    )

    op.create_table(
        "processing_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_type", sa.String(100), nullable=False),
        sa.Column("status", job_status, nullable=False),
        sa.Column("progress", sa.Float(), server_default="0", nullable=False),
        sa.Column("error_message", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "progress >= 0 AND progress <= 100", name="ck_processing_jobs_valid_progress"
        ),
    )
    op.create_index(
        "ix_processing_jobs_tenant_status", "processing_jobs", ["organization_id", "status"]
    )

    op.create_table(
        "conversations",
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
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("language", sa.String(8), nullable=False),
        *timestamps(),
    )
    op.create_index("ix_conversations_tenant_user", "conversations", ["organization_id", "user_id"])

    op.create_table(
        "messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", message_role, nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("language", sa.String(8), nullable=False),
        sa.Column("audio_path", sa.String(1024)),
        sa.Column("generation_status", generation_status, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_messages_conversation_created", "messages", ["conversation_id", "created_at"]
    )

    op.create_table(
        "message_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "message_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "document_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("document_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "chunk_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("document_chunks.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("relevance_score", sa.Float(), nullable=False),
        sa.Column("page_number", sa.Integer()),
    )
    op.create_index(
        "ix_message_sources_message_score", "message_sources", ["message_id", "relevance_score"]
    )

    op.create_table(
        "ai_settings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
        ),
        sa.Column("llm_provider", sa.String(100), nullable=False),
        sa.Column("llm_model", sa.String(255), nullable=False),
        sa.Column("embedding_provider", sa.String(100), nullable=False),
        sa.Column("tts_provider", sa.String(100), nullable=False),
        sa.Column("stt_provider", sa.String(100), nullable=False),
        sa.Column("voice_id", sa.String(255)),
        sa.Column("default_language", sa.String(8), nullable=False),
        *timestamps(),
        sa.UniqueConstraint("organization_id", name="uq_ai_settings_organization"),
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_ai_settings_global ON ai_settings ((organization_id IS NULL)) WHERE organization_id IS NULL"
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
        sa.Column("action", sa.String(255), nullable=False),
        sa.Column("resource_type", sa.String(100), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True)),
        sa.Column(
            "metadata", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_audit_logs_tenant_created", "audit_logs", ["organization_id", "created_at"])


def downgrade() -> None:
    for table in [
        "audit_logs",
        "ai_settings",
        "message_sources",
        "messages",
        "conversations",
        "processing_jobs",
        "document_chunks",
    ]:
        op.drop_table(table)
    op.drop_constraint(
        "fk_documents_active_version_id_document_versions", "documents", type_="foreignkey"
    )
    for table in ["document_versions", "documents", "refresh_sessions", "users", "organizations"]:
        op.drop_table(table)
    for enum in [
        generation_status,
        message_role,
        job_status,
        processing_status,
        approval_status,
        document_status,
        user_role,
    ]:
        enum.drop(op.get_bind(), checkfirst=True)
