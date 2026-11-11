import asyncio
import json
from collections.abc import AsyncIterator
from typing import cast
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from qdrant_client import AsyncQdrantClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.dependencies import get_app_settings, get_current_user, get_db_session
from app.integrations.openai_client import OpenAIResponsesClient
from app.modules.conversations.models import Conversation, Message
from app.modules.conversations.schemas import (
    ChatRequest,
    ChatResponse,
    ConversationCreate,
    ConversationResponse,
    MessageResponse,
)
from app.modules.conversations.service import ChatStage, ConversationService
from app.modules.knowledge_base.service import KnowledgeBaseService
from app.modules.rag.reranker import create_reranker
from app.modules.rag.service import RAGService
from app.modules.users.models import User
from app.modules.videos.service import VideoMatcher

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["conversations"])


def service(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_app_settings),
) -> ConversationService:
    knowledge_base = KnowledgeBaseService(
        settings, cast(AsyncQdrantClient, request.app.state.qdrant)
    )
    rag = RAGService(settings, knowledge_base, create_reranker(settings))
    return ConversationService(
        session, rag, OpenAIResponsesClient(settings), VideoMatcher(session, settings)
    )


@router.post("/conversations", response_model=ConversationResponse, status_code=201)
async def create_conversation(
    data: ConversationCreate,
    actor: User = Depends(get_current_user),
    conversations: ConversationService = Depends(service),
) -> Conversation:
    return await conversations.create(actor, data)


@router.get("/conversations", response_model=list[ConversationResponse])
async def list_conversations(
    actor: User = Depends(get_current_user),
    conversations: ConversationService = Depends(service),
) -> list[Conversation]:
    return await conversations.list_conversations(actor)


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageResponse])
async def list_messages(
    conversation_id: UUID,
    actor: User = Depends(get_current_user),
    conversations: ConversationService = Depends(service),
) -> list[Message]:
    return await conversations.messages(actor, conversation_id)


@router.post("/chat/messages", response_model=ChatResponse)
async def send_message(
    data: ChatRequest,
    actor: User = Depends(get_current_user),
    conversations: ConversationService = Depends(service),
) -> ChatResponse:
    return await conversations.send(actor, data)


def _sse(event: str, payload: object) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/chat/messages/stream")
async def stream_message(
    data: ChatRequest,
    actor: User = Depends(get_current_user),
    conversations: ConversationService = Depends(service),
) -> StreamingResponse:
    """Stream progress while the grounded answer is produced.

    Events: ``status`` (stage: rewriting | retrieving | generating | validating), then
    ``metadata``, ``text_delta`` chunks and ``completed``. The answer text is only sent
    after citation validation, so ungrounded model output never reaches the client. Errors
    after the stream has started arrive as an ``error`` event with ``status_code``.
    """
    stages: asyncio.Queue[ChatStage] = asyncio.Queue()

    async def on_stage(stage: ChatStage) -> None:
        await stages.put(stage)

    async def events() -> AsyncIterator[str]:
        task = asyncio.create_task(conversations.send(actor, data, on_stage=on_stage))
        try:
            while not task.done() or not stages.empty():
                getter = asyncio.ensure_future(stages.get())
                done, _ = await asyncio.wait({getter, task}, return_when=asyncio.FIRST_COMPLETED)
                if getter in done:
                    yield _sse("status", {"stage": getter.result()})
                else:
                    getter.cancel()
            try:
                result = task.result()
            except HTTPException as exc:
                yield _sse("error", {"status_code": exc.status_code, "detail": exc.detail})
                return
            except Exception:
                logger.exception("chat_stream_failed")
                yield _sse("error", {"status_code": 500, "detail": "Internal server error"})
                return
        finally:
            if not task.done():
                task.cancel()
        yield _sse(
            "metadata",
            {
                "conversation_id": str(result.conversation_id),
                "message_id": str(result.message_id),
                "model": result.model,
                "status": result.generation_status,
                "standalone_query": result.standalone_query,
            },
        )
        for offset in range(0, len(result.answer), 80):
            yield _sse("text_delta", {"delta": result.answer[offset : offset + 80]})
            await asyncio.sleep(0)
        yield _sse("completed", result.model_dump(mode="json"))

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
