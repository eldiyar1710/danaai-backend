from uuid import UUID

from pydantic import BaseModel

from app.modules.conversations.schemas import ChatResponse


class VoiceAudioResponse(BaseModel):
    url: str
    content_type: str
    provider: str
    model: str
    voice: str
    ai_generated: bool = True


class VoiceChatResponse(ChatResponse):
    transcript: str
    spoken_text: str
    audio: VoiceAudioResponse


class VoiceAudioMetadataResponse(BaseModel):
    message_id: UUID
    spoken_text: str
    audio_url: str
    content_type: str
