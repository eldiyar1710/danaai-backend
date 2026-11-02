import asyncio
import re
from io import BytesIO
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from minio import Minio

from app.core.config import Settings
from app.integrations.openai_audio import AudioProviderError
from app.integrations.voice_audio import VoiceAudioClient
from app.modules.conversations.models import Message, MessageRole
from app.modules.conversations.schemas import ChatRequest
from app.modules.conversations.service import ConversationService
from app.modules.users.models import User
from app.modules.voice.schemas import VoiceAudioResponse, VoiceChatResponse
from app.modules.voice.validation import validate_audio


class VoiceService:
    def __init__(
        self,
        settings: Settings,
        storage: Minio,
        conversations: ConversationService,
        audio: VoiceAudioClient,
    ) -> None:
        self.settings = settings
        self.storage = storage
        self.conversations = conversations
        self.audio = audio

    async def ask(
        self,
        actor: User,
        *,
        filename: str,
        content: bytes,
        declared_mime: str | None,
        conversation_id: UUID | None,
        organization_id: UUID | None,
        response_language: Literal["kk", "ru", "en"] | None,
    ) -> VoiceChatResponse:
        content_type = validate_audio(
            filename, content, declared_mime, self.settings.max_audio_upload_size_bytes
        )
        try:
            transcript = await self.audio.transcribe(
                filename=filename, content=content, content_type=content_type
            )
        except AudioProviderError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Speech transcription provider failed",
            ) from exc
        tenant_id = self.conversations.rag.knowledge_base.tenant(actor, organization_id)
        input_path = f"{tenant_id}/{actor.id}/{uuid4()}/question{Path(filename).suffix.lower()}"
        await self._put(input_path, content, content_type)
        chat = await self.conversations.send(
            actor,
            ChatRequest(
                query=transcript,
                conversation_id=conversation_id,
                organization_id=organization_id,
                response_language=response_language,
            ),
            user_audio_path=input_path,
        )
        spoken_answer = self._spoken_text(chat.answer)
        try:
            output = await self.audio.synthesize(spoken_answer)
        except AudioProviderError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Speech synthesis provider failed",
            ) from exc
        output_path = (
            f"{tenant_id}/{actor.id}/{chat.conversation_id}/{chat.message_id}/"
            f"answer.{output.extension}"
        )
        await self._put(output_path, output.content, output.content_type)
        await self.conversations.attach_audio(actor, chat.message_id, output_path)
        return VoiceChatResponse(
            **chat.model_dump(),
            transcript=transcript,
            spoken_text=spoken_answer,
            audio=VoiceAudioResponse(
                url=f"{self.settings.api_v1_prefix}/voice/messages/{chat.message_id}/audio",
                content_type=output.content_type,
                provider=output.provider,
                model=output.model,
                voice=output.voice,
            ),
        )

    async def audio_response(self, actor: User, message_id: UUID) -> tuple[bytes, str]:
        message = await self._audio_message(actor, message_id)
        assert message.audio_path is not None
        try:
            response = await asyncio.to_thread(
                self.storage.get_object, self.settings.minio_audio_bucket, message.audio_path
            )
            try:
                content = await asyncio.to_thread(response.read)
            finally:
                response.close()
                response.release_conn()
        except Exception as exc:
            raise HTTPException(status_code=502, detail="Audio storage request failed") from exc
        return content, self._audio_content_type(message)

    async def audio_metadata(self, actor: User, message_id: UUID) -> tuple[str, str]:
        message = await self._audio_message(actor, message_id)
        return self._spoken_text(message.content), self._audio_content_type(message)

    async def _audio_message(self, actor: User, message_id: UUID) -> Message:
        message = await self.conversations.audio_message(actor, message_id)
        if (
            message.role != MessageRole.ASSISTANT
            or not message.audio_path
            or not Path(message.audio_path).name.startswith("answer.")
        ):
            raise HTTPException(status_code=404, detail="Audio response not found")
        return message

    @staticmethod
    def _audio_content_type(message: Message) -> str:
        return (
            "audio/mpeg"
            if message.audio_path and message.audio_path.endswith(".mp3")
            else "audio/wav"
        )

    async def _put(self, path: str, content: bytes, content_type: str) -> None:
        bucket = self.settings.minio_audio_bucket

        def upload() -> None:
            if not self.storage.bucket_exists(bucket):
                self.storage.make_bucket(bucket)
            self.storage.put_object(
                bucket,
                path,
                BytesIO(content),
                length=len(content),
                content_type=content_type,
            )

        await asyncio.to_thread(upload)

    @staticmethod
    def _spoken_text(answer: str) -> str:
        without_citations = re.sub(r"\s*\[S\d+\]", "", answer)
        return re.sub(r"[*_`#]", "", without_citations).strip()
