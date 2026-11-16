import io
import struct
import wave

import pytest

from robot_client.g1_bridge import ask_server, pcm_rms, pcm_to_wav, play_pcm


def test_microphone_pcm_is_packaged_as_16khz_mono_wav() -> None:
    pcm = struct.pack("<4h", 0, 1000, -1000, 0)
    assert pcm_rms(pcm) > 700
    with wave.open(io.BytesIO(pcm_to_wav(pcm))) as reader:
        assert (reader.getframerate(), reader.getnchannels(), reader.getsampwidth()) == (
            16000,
            1,
            2,
        )
        assert reader.readframes(4) == pcm


def test_playback_stops_even_if_unitree_rejects_a_chunk(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("robot_client.g1_bridge.time.sleep", lambda _: None)

    class Client:
        stopped = False

        def PlayStream(self, app_name: str, stream_id: str, pcm: bytes) -> int:
            assert app_name == "danaai-university"
            return 7

        def PlayStop(self, app_name: str) -> int:
            self.stopped = True
            return 0

    client = Client()
    with pytest.raises(RuntimeError, match="code 7"):
        play_pcm(client, b"\x00\x00")
    assert client.stopped


async def test_bridge_rejects_public_plain_http() -> None:
    with pytest.raises(ValueError, match="isolated G1 network"):
        await ask_server("http://8.8.8.8:18000", "key", b"wav", None)
