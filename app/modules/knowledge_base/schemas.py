from uuid import UUID

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=2000)
    organization_id: UUID | None = None
    limit: int = Field(default=10, ge=1, le=50)


class SearchHit(BaseModel):
    chunk_id: UUID
    document_id: UUID
    document_version_id: UUID
    text: str
    score: float
    page_number: int | None = None
    section_title: str | None = None


class SearchResponse(BaseModel):
    results: list[SearchHit]


class KnowledgeBaseStats(BaseModel):
    organization_id: UUID
    active_chunks: int
