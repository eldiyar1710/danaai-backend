"""Cascade message-source references when a document is deliberately deleted.

Revision ID: 20261031_0003
Revises: 20261030_0002
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261031_0003"
down_revision: str | None = "20261030_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FOREIGN_KEYS = (
    (
        "fk_message_sources_document_id_documents",
        "documents",
        ["document_id"],
        ["id"],
    ),
    (
        "fk_message_sources_document_version_id_document_versions",
        "document_versions",
        ["document_version_id"],
        ["id"],
    ),
    (
        "fk_message_sources_chunk_id_document_chunks",
        "document_chunks",
        ["chunk_id"],
        ["id"],
    ),
)


def _replace(ondelete: str) -> None:
    for name, target, local_columns, remote_columns in _FOREIGN_KEYS:
        op.drop_constraint(name, "message_sources", type_="foreignkey")
        op.create_foreign_key(
            name,
            "message_sources",
            target,
            local_columns,
            remote_columns,
            ondelete=ondelete,
        )


def upgrade() -> None:
    _replace("CASCADE")


def downgrade() -> None:
    _replace("RESTRICT")
