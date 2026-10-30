from typing import cast

from fastapi import APIRouter, Depends, Request
from qdrant_client import AsyncQdrantClient

from app.core.config import Settings
from app.core.dependencies import get_app_settings, get_current_user
from app.modules.knowledge_base.service import KnowledgeBaseService
from app.modules.rag.reranker import create_reranker
from app.modules.rag.schemas import RAGRetrieveRequest, RAGRetrieveResponse
from app.modules.rag.service import RAGService
from app.modules.users.models import User

router = APIRouter(prefix="/rag", tags=["rag"])


def service(request: Request, settings: Settings = Depends(get_app_settings)) -> RAGService:
    knowledge_base = KnowledgeBaseService(
        settings, cast(AsyncQdrantClient, request.app.state.qdrant)
    )
    return RAGService(settings, knowledge_base, create_reranker(settings))


@router.post("/retrieve", response_model=RAGRetrieveResponse)
async def retrieve(
    data: RAGRetrieveRequest,
    actor: User = Depends(get_current_user),
    rag: RAGService = Depends(service),
) -> RAGRetrieveResponse:
    return await rag.retrieve(actor, data)
