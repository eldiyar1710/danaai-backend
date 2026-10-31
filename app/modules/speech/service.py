import wave
from io import BytesIO

from fastapi import HTTPException, status

from app.core.config import Settings
from app.integrations.openai_audio import AudioProviderError
from app.integrations.voice_audio import SynthesizedAudio, VoiceAudioClient
from app.modules.rag.language import Language, detect_language
from app.modules.speech.schemas import SpeechVoice, SynthesisRequest, TranscriptionResponse
from app.modules.voice.validation import validate_audio

_OPENAI_VOICES = (
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
)


class SpeechService:
    def __init__(self, settings: Settings, audio: VoiceAudioClient) -> None:
        self.settings = settings
        self.audio = audio

    async def transcribe(
        self,
        *,
        filename: str,
        content: bytes,
        declared_mime: str | None,
        language: Language | None,
    ) -> TranscriptionResponse:
        content_type = validate_audio(
            filename, content, declared_mime, self.settings.max_audio_upload_size_bytes
        )
        try:
            result = await self.audio.transcribe_result(
                filename=filename,
                content=content,
                content_type=content_type,
                language=language,
            )
        except AudioProviderError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Speech transcription provider failed",
            ) from exc
        return TranscriptionResponse(
            text=result.text,
            language=language or detect_language(result.text, self.settings.default_language),
            duration_seconds=self._wav_duration(content, content_type),
            provider=result.provider,
            model=result.model,
        )

    async def synthesize(self, data: SynthesisRequest) -> SynthesizedAudio:
        try:
            return await self.audio.synthesize(
                data.text,
                voice_id=data.voice_id,
                speed=data.speed,
                output_format=data.output_format,
            )
        except AudioProviderError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Speech synthesis provider failed",
            ) from exc

    def voices(self) -> list[SpeechVoice]:
        voices: list[SpeechVoice] = []
        if self.settings.elevenlabs_voice_id:
            voices.append(
                SpeechVoice(
                    voice_id=self.settings.elevenlabs_voice_id,
                    name="Configured ElevenLabs voice",
                    provider="elevenlabs",
                    languages=["kk", "ru", "en"],
                    configured=self.audio.elevenlabs.configured_for_tts,
                )
            )
        voices.extend(
            SpeechVoice(
                voice_id=voice,
                name=voice.title(),
                provider="openai",
                languages=["kk", "ru", "en"],
                configured=self.settings.openai_api_key is not None,
            )
            for voice in _OPENAI_VOICES
        )
        return voices

    @staticmethod
    def _wav_duration(content: bytes, content_type: str) -> float | None:
        if content_type != "audio/wav":
            return None
        try:
            with wave.open(BytesIO(content), "rb") as audio:
                return round(audio.getnframes() / audio.getframerate(), 3)
        except (EOFError, wave.Error, ZeroDivisionError):
            return None
