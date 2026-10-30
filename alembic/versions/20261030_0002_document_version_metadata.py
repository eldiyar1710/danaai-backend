"""Add immutable file metadata to document versions.

Revision ID: 20261030_0002
Revises: 20261029_0001
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261030_0002"
down_revision: str | None = "20261029_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "document_versions", sa.Column("original_filename", sa.String(500), nullable=True)
    )
    op.add_column("document_versions", sa.Column("mime_type", sa.String(255), nullable=True))
    op.add_column("document_versions", sa.Column("size_bytes", sa.BigInteger(), nullable=True))
    op.add_column("document_versions", sa.Column("language", sa.String(8), nullable=True))
    op.execute(
        """
        UPDATE document_versions AS version
        SET original_filename = document.original_filename,
            mime_type = document.mime_type,
            size_bytes = document.size_bytes,
            language = document.language
        FROM documents AS document
        WHERE version.document_id = document.id
        """
    )
    op.alter_column("document_versions", "original_filename", nullable=False)
    op.alter_column("document_versions", "mime_type", nullable=False)
    op.alter_column("document_versions", "size_bytes", nullable=False)
    op.alter_column("document_versions", "language", nullable=False)
    op.create_check_constraint("positive_size", "document_versions", "size_bytes > 0")


def downgrade() -> None:
    op.drop_constraint("ck_document_versions_positive_size", "document_versions", type_="check")
    op.drop_column("document_versions", "size_bytes")
    op.drop_column("document_versions", "language")
    op.drop_column("document_versions", "mime_type")
    op.drop_column("document_versions", "original_filename")
