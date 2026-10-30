from uuid import UUID

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, TimestampMixin, UUIDPrimaryKeyMixin


class AISettings(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_settings"
    __table_args__ = (
        UniqueConstraint("organization_id", name="uq_ai_settings_organization"),
        Index(
            "uq_ai_settings_global",
            text("(organization_id IS NULL)"),
            unique=True,
            postgresql_where=text("organization_id IS NULL"),
        ),
    )

    organization_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE")
    )
    llm_provider: Mapped[str] = mapped_column(String(100))
    llm_model: Mapped[str] = mapped_column(String(255))
    embedding_provider: Mapped[str] = mapped_column(String(100))
    tts_provider: Mapped[str] = mapped_column(String(100))
    stt_provider: Mapped[str] = mapped_column(String(100))
    voice_id: Mapped[str | None] = mapped_column(String(255))
    default_language: Mapped[str] = mapped_column(String(8), default="ru")
