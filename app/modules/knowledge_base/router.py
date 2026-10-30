from typing import cast
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from qdrant_client import AsyncQdrantClient

from app.core.config import Settings
from app.core.dependencies import get_app_settings, get_current_user
from app.modules.knowledge_base.schemas import (
    KnowledgeBaseStats,
    SearchRequest,
    SearchResponse,
)
from app.modules.knowledge_base.service import KnowledgeBaseService
from app.modules.users.models import User

router = APIRouter(prefix="/knowledge-base", tags=["knowledge-base"])


def service(
    request: Request, settings: Settings = Depends(get_app_settings)
) -> KnowledgeBaseService:
    return KnowledgeBaseService(settings, cast(AsyncQdrantClient, request.app.state.qdrant))


@router.post("/search", response_model=SearchResponse)
async def search(
    data: SearchRequest,
    actor: User = Depends(get_current_user),
    knowledge_base: KnowledgeBaseService = Depends(service),
) -> SearchResponse:
    return await knowledge_base.search(actor, data)


@router.get("/stats", response_model=KnowledgeBaseStats)
async def stats(
    organization_id: UUID | None = None,
    actor: User = Depends(get_current_user),
    knowledge_base: KnowledgeBaseService = Depends(service),
) -> KnowledgeBaseStats:
    return await knowledge_base.stats(actor, organization_id)
