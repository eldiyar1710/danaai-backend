from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


def _clean_questions(value: list[str] | None) -> list[str] | None:
    if value is None:
        return None
    questions = [item.strip() for item in value if item and item.strip()]
    if len(questions) > 30:
        raise ValueError("At most 30 example questions are allowed")
    if any(len(question) > 500 for question in questions):
        raise ValueError("Example questions must be at most 500 characters")
    return list(dict.fromkeys(questions))


class VideoUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=500)
    description: str | None = Field(default=None, max_length=5000)
    example_questions: list[str] | None = None
    linked_document_ids: list[UUID] | None = None
    language: str | None = Field(default=None, pattern="^(kk|ru|en)$")

    _questions = field_validator("example_questions")(_clean_questions)


class VideoRead(BaseModel):
    id: UUID
    organization_id: UUID
    title: str
    description: str
    example_questions: list[str]
    language: str
    linked_document_ids: list[UUID]
    original_filename: str
    mime_type: str
    size_bytes: int
    duration_seconds: float | None
    width: int | None
    height: int | None
    status: str
    error_message: str | None
    approved_by_id: UUID | None
    approved_at: datetime | None
    created_at: datetime
    stream_url: str | None = Field(
        default=None, description="Signed URL usable directly in <video src>, expires"
    )
    thumbnail_url: str | None = None


class VideoSuggestion(BaseModel):
    """A video attached to a grounded answer."""

    id: UUID
    title: str
    description: str
    duration_seconds: float | None
    width: int | None
    height: int | None
    mime_type: str
    stream_url: str = Field(description="Signed URL usable directly in <video src>, expires")
    thumbnail_url: str | None
    expires_at: datetime
    score: float = Field(description="Similarity of the question to the video card")
    linked_document_ids: list[UUID] = Field(description="Cited documents this video illustrates")
