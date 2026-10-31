from app.modules.conversations.models import Message, MessageSource


def test_message_created_at_uses_database_default() -> None:
    assert Message.__table__.c.created_at.server_default is not None


def test_message_sources_are_removed_with_deleted_source_records() -> None:
    for column_name in ("document_id", "document_version_id", "chunk_id"):
        foreign_key = next(iter(MessageSource.__table__.c[column_name].foreign_keys))
        assert foreign_key.ondelete == "CASCADE"
