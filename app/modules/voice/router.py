from typing import Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile
from fastapi.responses import JSONResponse
from minio import Minio
from qdrant_client import AsyncQdrantClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.dependencies import get_app_settings, get_current_user, get_db_session
from app.integrations.openai_client import OpenAIResponsesClient
from app.integrations.voice_audio import VoiceAudioClient
from app.modules.conversations.service import ConversationService
from app.modules.knowledge_base.service import KnowledgeBaseService
from app.modules.rag.reranker import create_reranker
from app.modules.rag.service import RAGService
from app.modules.users.models import User
from app.modules.voice.schemas import VoiceAudioMetadataResponse, VoiceChatResponse
from app.modules.voice.service import VoiceService

router = APIRouter(prefix="/voice", tags=["voice-agent"])


def service(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_app_settings),
) -> VoiceService:
    knowledge_base = KnowledgeBaseService(
        settings, cast(AsyncQdrantClient, request.app.state.qdrant)
    )
    rag = RAGService(settings, knowledge_base, create_reranker(settings))
    conversations = ConversationService(session, rag, OpenAIResponsesClient(settings))
    return VoiceService(
        settings,
        cast(Minio, request.app.state.minio),
        conversations,
        VoiceAudioClient(settings),
    )


@router.post("/ask", response_model=VoiceChatResponse)
async def ask_voice_agent(
    file: UploadFile = File(...),
    conversation_id: UUID | None = Form(None),
    organization_id: UUID | None = Form(None),
    response_language: Literal["kk", "ru", "en"] | None = Form(None),
    actor: User = Depends(get_current_user),
    voice: VoiceService = Depends(service),
) -> VoiceChatResponse:
    content = await file.read(voice.settings.max_audio_upload_size_bytes + 1)
    return await voice.ask(
        actor,
        filename=file.filename or "audio",
        content=content,
        declared_mime=file.content_type,
        conversation_id=conversation_id,
        organization_id=organization_id,
        response_language=response_language,
    )


@router.get("/messages/{message_id}/audio")
async def get_voice_answer(
    message_id: UUID,
    metadata: bool = False,
    actor: User = Depends(get_current_user),
    voice: VoiceService = Depends(service),
) -> Response:
    if metadata:
        spoken_text, content_type = await voice.audio_metadata(actor, message_id)
        payload = VoiceAudioMetadataResponse(
            message_id=message_id,
            spoken_text=spoken_text,
            audio_url=f"{voice.settings.api_v1_prefix}/voice/messages/{message_id}/audio",
            content_type=content_type,
        )
        return JSONResponse(content=payload.model_dump(mode="json"))
    content, content_type = await voice.audio_response(actor, message_id)
    return Response(
        content=content,
        media_type=content_type,
        headers={
            "Content-Disposition": f'inline; filename="voice-answer-{message_id}"',
            "X-AI-Generated-Voice": "true",
        },
    )
