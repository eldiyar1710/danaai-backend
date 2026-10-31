from pydantic import SecretStr

from app.core.config import Settings
from app.integrations.elevenlabs_audio import ElevenLabsAudioClient


def test_elevenlabs_dialogue_url_uses_v4_turbo() -> None:
    client = ElevenLabsAudioClient(
        Settings(
            elevenlabs_api_key=SecretStr("test-key"),
            elevenlabs_voice_id="voice-123",
        )
    )
    assert client.configured_for_stt is True
    assert client.configured_for_tts is True
    assert client._dialogue_url() == (
        "wss://api.elevenlabs.io/v1/text-to-dialogue/stream-input"
        "?model_id=eleven_v4_turbo&output_format=mp3_44100_128"
    )


def test_elevenlabs_requires_voice_id_only_for_tts() -> None:
    client = ElevenLabsAudioClient(
        Settings(
            _env_file=None,
            elevenlabs_api_key=SecretStr("test-key"),
            elevenlabs_voice_id=None,
        )
    )
    assert client.configured_for_stt is True
    assert client.configured_for_tts is False
