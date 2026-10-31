import wave
from io import BytesIO
from unittest.mock import AsyncMock

from app.core.config import Settings
from app.integrations.voice_audio import SynthesizedAudio, TranscriptionResult, VoiceAudioClient
from app.modules.speech.schemas import SynthesisRequest
from app.modules.speech.service import SpeechService


def _wav() -> bytes:
    output = BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"\x00\x00" * 8000)
    return output.getvalue()


async def test_transcribe_reports_language_provider_and_duration() -> None:
    settings = Settings(_env_file=None)
    audio = VoiceAudioClient(settings)
    audio.transcribe_result = AsyncMock(
        return_value=TranscriptionResult(
            text="Қауіпсіздік ережесі", provider="elevenlabs", model="scribe_v2"
        )
    )
    service = SpeechService(settings, audio)

    result = await service.transcribe(
        filename="question.wav",
        content=_wav(),
        declared_mime="audio/wav",
        language=None,
    )

    assert result.language == "kk"
    assert result.provider == "elevenlabs"
    assert result.duration_seconds == 1.0


async def test_synthesize_returns_actual_audio_metadata() -> None:
    settings = Settings(_env_file=None)
    audio = VoiceAudioClient(settings)
    audio.synthesize = AsyncMock(
        return_value=SynthesizedAudio(
            content=b"audio",
            content_type="audio/mpeg",
            extension="mp3",
            provider="elevenlabs",
            model="eleven_v4_turbo",
            voice="voice-id",
        )
    )
    service = SpeechService(settings, audio)

    result = await service.synthesize(SynthesisRequest(text="Сәлем", output_format="mp3"))

    assert result.content == b"audio"
    assert result.provider == "elevenlabs"


def test_voice_catalog_contains_configured_elevenlabs_and_openai_fallbacks() -> None:
    settings = Settings(
        _env_file=None,
        elevenlabs_voice_id="voice-id",
        elevenlabs_api_key="test-key",
    )
    service = SpeechService(settings, VoiceAudioClient(settings))

    voices = service.voices()

    assert voices[0].voice_id == "voice-id"
    assert voices[0].configured is True
    assert any(voice.voice_id == "marin" for voice in voices)
