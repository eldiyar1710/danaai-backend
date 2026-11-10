from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.modules.rag.schemas import CitationValidation, RAGSource


class ConversationCreate(BaseModel):
    title: str | None = Field(default=None, max_length=500)
    language: Literal["kk", "ru", "en"] = "ru"
    organization_id: UUID | None = None


class ConversationResponse(BaseModel):
    id: UUID
    organization_id: UUID
    user_id: UUID
    title: str
    language: str
    created_at: datetime

    model_config = {"from_attributes": True}


class MessageResponse(BaseModel):
    id: UUID
    conversation_id: UUID
    role: str
    content: str
    language: str
    generation_status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ChatRequest(BaseModel):
    query: str = Field(min_length=2, max_length=2000)
    conversation_id: UUID | None = None
    organization_id: UUID | None = None
    response_language: Literal["kk", "ru", "en"] | None = None


class TokenUsage(BaseModel):
    input_tokens: int
    output_tokens: int
    reasoning_tokens: int


class ChatResponse(BaseModel):
    conversation_id: UUID
    message_id: UUID
    answer: str
    language: Literal["kk", "ru", "en"]
    generation_status: str
    model: str | None = None
    usage: TokenUsage
    sources: list[RAGSource]
    citation_validation: CitationValidation
    standalone_query: str | None = Field(
        default=None,
        description="Follow-up question rewritten with conversation history for retrieval",
    )
