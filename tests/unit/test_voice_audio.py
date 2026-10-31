from unittest.mock import AsyncMock

from app.core.config import Settings
from app.integrations.voice_audio import VoiceAudioClient


async def test_openai_fallback_is_used_without_elevenlabs_credentials() -> None:
    client = VoiceAudioClient(Settings(_env_file=None))
    client.openai.transcribe = AsyncMock(return_value="Қауіпсіздік деген не?")
    result = await client.transcribe(
        filename="question.wav", content=b"audio", content_type="audio/wav"
    )
    assert result == "Қауіпсіздік деген не?"
    client.openai.transcribe.assert_awaited_once()


async def test_openai_tts_fallback_reports_actual_format() -> None:
    client = VoiceAudioClient(Settings(_env_file=None))
    client.openai.synthesize = AsyncMock(return_value=b"RIFFaudio")
    result = await client.synthesize("Жауап")
    assert result.content == b"RIFFaudio"
    assert result.content_type == "audio/wav"
    assert result.provider == "openai"


async def test_openai_voice_selection_does_not_call_elevenlabs() -> None:
    client = VoiceAudioClient(Settings(_env_file=None))
    client.elevenlabs.synthesize = AsyncMock()
    client.openai.synthesize = AsyncMock(return_value=b"RIFFaudio")

    result = await client.synthesize("Жауап", voice_id="coral")

    client.elevenlabs.synthesize.assert_not_awaited()
    client.openai.synthesize.assert_awaited_once_with("Жауап", voice="coral", speed=None)
    assert result.voice == "coral"
