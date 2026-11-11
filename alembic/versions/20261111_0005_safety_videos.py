"""Add safety training videos linked to approved documents.

Revision ID: 20261111_0005
Revises: 20261109_0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20261111_0005"
down_revision: str | None = "20261109_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

video_status = postgresql.ENUM(
    "PROCESSING",
    "READY",
    "APPROVED",
    "ARCHIVED",
    "FAILED",
    name="video_status",
    create_type=False,
)


def upgrade() -> None:
    video_status.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "safety_videos",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "example_questions",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("language", sa.String(2), nullable=False, server_default="ru"),
        sa.Column("original_filename", sa.String(500), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("minio_path", sa.String(1000), nullable=False),
        sa.Column("thumbnail_path", sa.String(1000), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("status", video_status, nullable=False, server_default="PROCESSING"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("embeddings", postgresql.JSONB(), nullable=True),
        sa.Column("embedding_model", sa.String(255), nullable=True),
        sa.Column(
            "created_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "approved_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_safety_videos_tenant_status", "safety_videos", ["organization_id", "status"]
    )
    op.create_table(
        "safety_video_documents",
        sa.Column(
            "video_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("safety_videos.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    op.create_index("ix_safety_video_documents_document", "safety_video_documents", ["document_id"])


def downgrade() -> None:
    op.drop_index("ix_safety_video_documents_document", table_name="safety_video_documents")
    op.drop_table("safety_video_documents")
    op.drop_index("ix_safety_videos_tenant_status", table_name="safety_videos")
    op.drop_table("safety_videos")
    video_status.drop(op.get_bind(), checkfirst=True)
