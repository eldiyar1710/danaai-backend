from dataclasses import dataclass

import structlog

from app.core.config import Settings
from app.integrations.elevenlabs_audio import ElevenLabsAudioClient
from app.integrations.openai_audio import AudioProviderError, OpenAIAudioClient

logger = structlog.get_logger(__name__)
_OPENAI_VOICES = {
    "alloy",
    "ash",
    "ballad",
    "coral",
    "echo",
    "sage",
    "shimmer",
    "verse",
    "marin",
    "cedar",
}


@dataclass(frozen=True)
class SynthesizedAudio:
    content: bytes
    content_type: str
    extension: str
    provider: str
    model: str
    voice: str


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    provider: str
    model: str


class VoiceAudioClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.elevenlabs = ElevenLabsAudioClient(settings)
        self.openai = OpenAIAudioClient(settings)

    async def transcribe_result(
        self,
        *,
        filename: str,
        content: bytes,
        content_type: str,
        language: str | None = None,
    ) -> TranscriptionResult:
        if self.settings.stt_provider == "elevenlabs" and self.elevenlabs.configured_for_stt:
            try:
                text = await self.elevenlabs.transcribe(
                    filename=filename,
                    content=content,
                    content_type=content_type,
                    language=language,
                )
                return TranscriptionResult(
                    text=text,
                    provider="elevenlabs",
                    model=self.settings.elevenlabs_stt_model,
                )
            except AudioProviderError as exc:
                logger.warning("elevenlabs_stt_fallback", error=type(exc).__name__)
        text = await self.openai.transcribe(
            filename=filename,
            content=content,
            content_type=content_type,
            language=language,
        )
        return TranscriptionResult(text=text, provider="openai", model=self.settings.stt_model)

    async def transcribe(
        self,
        *,
        filename: str,
        content: bytes,
        content_type: str,
        language: str | None = None,
    ) -> str:
        result = await self.transcribe_result(
            filename=filename,
            content=content,
            content_type=content_type,
            language=language,
        )
        return result.text

    async def synthesize(
        self,
        text: str,
        *,
        voice_id: str | None = None,
        speed: float | None = None,
        output_format: str | None = None,
    ) -> SynthesizedAudio:
        openai_voice = voice_id if voice_id in _OPENAI_VOICES else None
        use_elevenlabs = self.settings.tts_provider == "elevenlabs" and bool(
            self.elevenlabs.configured_for_stt
            and (voice_id or self.settings.elevenlabs_voice_id)
            and openai_voice is None
            and output_format != "wav"
        )
        if use_elevenlabs:
            try:
                selected_voice = voice_id or str(self.settings.elevenlabs_voice_id)
                content = await self.elevenlabs.synthesize(
                    text,
                    voice_id=selected_voice,
                    output_format=("mp3_44100_128" if output_format == "mp3" else None),
                )
                return SynthesizedAudio(
                    content=content,
                    content_type="audio/mpeg",
                    extension="mp3",
                    provider="elevenlabs",
                    model=self.settings.elevenlabs_tts_model,
                    voice=selected_voice,
                )
            except AudioProviderError as exc:
                logger.warning("elevenlabs_tts_fallback", error=type(exc).__name__)
        content = await self.openai.synthesize(text, voice=openai_voice, speed=speed)
        selected_voice = openai_voice or self.settings.tts_voice
        return SynthesizedAudio(
            content=content,
            content_type="audio/wav",
            extension="wav",
            provider="openai",
            model=self.settings.tts_model,
            voice=selected_voice,
        )
