import enum
from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, TimestampMixin, UUIDPrimaryKeyMixin


class MessageRole(enum.StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class GenerationStatus(enum.StrEnum):
    PENDING = "pending"
    ANSWERED = "answered"
    INSUFFICIENT_CONTEXT = "insufficient_context"
    FAILED = "failed"


class Conversation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conversations_tenant_user", "organization_id", "user_id"),)

    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE")
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    title: Mapped[str] = mapped_column(String(500))
    language: Mapped[str] = mapped_column(String(8))


class Message(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_conversation_created", "conversation_id", "created_at"),)

    conversation_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE")
    )
    role: Mapped[MessageRole] = mapped_column(Enum(MessageRole, name="message_role"))
    content: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(8))
    audio_path: Mapped[str | None] = mapped_column(String(1024))
    generation_status: Mapped[GenerationStatus] = mapped_column(
        Enum(GenerationStatus, name="generation_status")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MessageSource(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "message_sources"
    __table_args__ = (Index("ix_message_sources_message_score", "message_id", "relevance_score"),)

    message_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE")
    )
    document_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("documents.id", ondelete="RESTRICT")
    )
    document_version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("document_versions.id", ondelete="RESTRICT")
    )
    chunk_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("document_chunks.id", ondelete="RESTRICT")
    )
    relevance_score: Mapped[float] = mapped_column(Float)
    page_number: Mapped[int | None]
