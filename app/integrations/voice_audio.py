from dataclasses import dataclass

import structlog

from app.core.config import Settings
from app.integrations.elevenlabs_audio import ElevenLabsAudioClient
from app.integrations.openai_audio import AudioProviderError, OpenAIAudioClient

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class SynthesizedAudio:
    content: bytes
    content_type: str
    extension: str
    provider: str
    model: str
    voice: str


class VoiceAudioClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.elevenlabs = ElevenLabsAudioClient(settings)
        self.openai = OpenAIAudioClient(settings)

    async def transcribe(self, *, filename: str, content: bytes, content_type: str) -> str:
        if self.settings.stt_provider == "elevenlabs" and self.elevenlabs.configured_for_stt:
            try:
                return await self.elevenlabs.transcribe(
                    filename=filename, content=content, content_type=content_type
                )
            except AudioProviderError as exc:
                logger.warning("elevenlabs_stt_fallback", error=type(exc).__name__)
        return await self.openai.transcribe(
            filename=filename, content=content, content_type=content_type
        )

    async def synthesize(self, text: str) -> SynthesizedAudio:
        if self.settings.tts_provider == "elevenlabs" and self.elevenlabs.configured_for_tts:
            try:
                content = await self.elevenlabs.synthesize(text)
                return SynthesizedAudio(
                    content=content,
                    content_type="audio/mpeg",
                    extension="mp3",
                    provider="elevenlabs",
                    model=self.settings.elevenlabs_tts_model,
                    voice=str(self.settings.elevenlabs_voice_id),
                )
            except AudioProviderError as exc:
                logger.warning("elevenlabs_tts_fallback", error=type(exc).__name__)
        content = await self.openai.synthesize(text)
        return SynthesizedAudio(
            content=content,
            content_type="audio/wav",
            extension="wav",
            provider="openai",
            model=self.settings.tts_model,
            voice=self.settings.tts_voice,
        )
