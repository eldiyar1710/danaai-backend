from unittest.mock import AsyncMock

from app.core.config import Settings
from app.integrations.voice_audio import VoiceAudioClient


async def test_openai_fallback_is_used_without_elevenlabs_credentials() -> None:
    client = VoiceAudioClient(Settings())
    client.openai.transcribe = AsyncMock(return_value="Қауіпсіздік деген не?")
    result = await client.transcribe(
        filename="question.wav", content=b"audio", content_type="audio/wav"
    )
    assert result == "Қауіпсіздік деген не?"
    client.openai.transcribe.assert_awaited_once()


async def test_openai_tts_fallback_reports_actual_format() -> None:
    client = VoiceAudioClient(Settings())
    client.openai.synthesize = AsyncMock(return_value=b"RIFFaudio")
    result = await client.synthesize("Жауап")
    assert result.content == b"RIFFaudio"
    assert result.content_type == "audio/wav"
    assert result.provider == "openai"
