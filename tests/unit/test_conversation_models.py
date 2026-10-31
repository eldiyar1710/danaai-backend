from app.modules.conversations.models import Message


def test_message_created_at_uses_database_default() -> None:
    assert Message.__table__.c.created_at.server_default is not None
