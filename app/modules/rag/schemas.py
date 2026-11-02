from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class RAGRetrieveRequest(BaseModel):
    query: str = Field(min_length=2, max_length=2000)
    organization_id: UUID | None = None
    response_language: Literal["kk", "ru", "en"] | None = None


class RAGSource(BaseModel):
    citation_id: str
    chunk_id: UUID
    document_id: UUID
    document_version_id: UUID
    text: str
    retrieval_score: float
    rerank_score: float
    page_number: int | None = None
    section_title: str | None = None
    document_title: str | None = None
    document_url: str | None = None


class RAGRetrieveResponse(BaseModel):
    normalized_query: str
    detected_language: Literal["kk", "ru", "en"]
    response_language: Literal["kk", "ru", "en"]
    insufficient_context: bool
    context: str
    sources: list[RAGSource]
    excluded_suspicious_chunks: int
    warnings: list[str]


class CitationValidation(BaseModel):
    valid: bool
    citations: list[str]
    unknown_citations: list[str]
    missing_citations: bool
