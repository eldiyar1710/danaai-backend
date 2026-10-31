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
    audio: VoiceAudioResponse
