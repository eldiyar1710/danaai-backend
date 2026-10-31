import wave
from io import BytesIO

from app.core.config import Settings
from app.integrations.openai_audio import OpenAIAudioClient


def test_realtime_url_uses_configured_model() -> None:
    client = OpenAIAudioClient(
        Settings(
            openai_base_url="https://api.openai.com/v1",
            tts_model="gpt-realtime-2.1-mini",
        )
    )
    assert client._realtime_url() == (
        "wss://api.openai.com/v1/realtime?model=gpt-realtime-2.1-mini"
    )


def test_pcm_is_wrapped_as_24khz_mono_wav() -> None:
    content = OpenAIAudioClient._pcm_to_wav(b"\x00\x00" * 12)
    with wave.open(BytesIO(content), "rb") as wav:
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.getframerate() == 24000
        assert wav.getnframes() == 12
