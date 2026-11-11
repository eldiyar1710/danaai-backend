import enum
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, Enum, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, TimestampMixin, UUIDPrimaryKeyMixin


class VideoStatus(enum.StrEnum):
    PROCESSING = "processing"
    READY = "ready"
    APPROVED = "approved"
    ARCHIVED = "archived"
    FAILED = "failed"


class SafetyVideo(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A short training clip shown next to a grounded answer.

    A video is never a source of facts: it is suggested only when the answer already cites
    one of its linked documents and the question is semantically close to the video card
    (title, description and example questions).
    """

    __tablename__ = "safety_videos"
    __table_args__ = (Index("ix_safety_videos_tenant_status", "organization_id", "status"),)

    organization_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE")
    )
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text, default="")
    example_questions: Mapped[list[str]] = mapped_column(JSONB, default=list)
    language: Mapped[str] = mapped_column(String(2), default="ru")
    original_filename: Mapped[str] = mapped_column(String(500))
    mime_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    minio_path: Mapped[str] = mapped_column(String(1000))
    thumbnail_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[VideoStatus] = mapped_column(
        Enum(VideoStatus, name="video_status"), default=VideoStatus.PROCESSING
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    embeddings: Mapped[list[list[float]] | None] = mapped_column(JSONB, nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_by_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_by_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SafetyVideoDocument(Base):
    """Approved instruction a video illustrates; the video is shown only alongside it."""

    __tablename__ = "safety_video_documents"
    __table_args__ = (Index("ix_safety_video_documents_document", "document_id"),)

    video_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("safety_videos.id", ondelete="CASCADE"),
        primary_key=True,
    )
    document_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        primary_key=True,
    )


def card_texts(video: Any) -> list[str]:
    """Texts embedded for matching: the card itself plus each example question."""
    card = f"{video.title}\n{video.description}".strip()
    questions = [question.strip() for question in video.example_questions if question.strip()]
    return [card, *questions]
