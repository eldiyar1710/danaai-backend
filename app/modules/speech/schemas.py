from typing import Literal

from pydantic import BaseModel, Field

from app.modules.rag.language import Language


class TranscriptionResponse(BaseModel):
    text: str
    language: Language
    duration_seconds: float | None = None
    provider: str
    model: str


class SynthesisRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    language: Language | None = None
    voice_id: str | None = Field(default=None, min_length=1, max_length=255)
    speed: float | None = Field(default=None, ge=0.25, le=1.5)
    output_format: Literal["mp3", "wav"] | None = None


class SpeechVoice(BaseModel):
    voice_id: str
    name: str
    provider: Literal["elevenlabs", "openai"]
    languages: list[Language]
    configured: bool


class VoicesResponse(BaseModel):
    default_voice_id: str
    voices: list[SpeechVoice]
