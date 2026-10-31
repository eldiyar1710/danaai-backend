import base64
import json
from typing import Any
from urllib.parse import urlencode, urlparse, urlunparse

import httpx
from websockets.asyncio.client import connect

from app.core.config import Settings
from app.integrations.openai_audio import AudioProviderError


class ElevenLabsAudioClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def configured_for_stt(self) -> bool:
        return bool(self._optional_api_key())

    @property
    def configured_for_tts(self) -> bool:
        return bool(self._optional_api_key() and self.settings.elevenlabs_voice_id)

    def _optional_api_key(self) -> str:
        if self.settings.elevenlabs_api_key is None:
            return ""
        return self.settings.elevenlabs_api_key.get_secret_value().strip()

    def _api_key(self) -> str:
        value = self._optional_api_key()
        if not value:
            raise AudioProviderError("ELEVENLABS_API_KEY is not configured")
        return value

    def _voice_id(self) -> str:
        value = (self.settings.elevenlabs_voice_id or "").strip()
        if not value:
            raise AudioProviderError("ELEVENLABS_VOICE_ID is not configured")
        return value

    async def transcribe(
        self,
        *,
        filename: str,
        content: bytes,
        content_type: str,
        language: str | None = None,
    ) -> str:
        url = f"{str(self.settings.elevenlabs_base_url).rstrip('/')}/speech-to-text"
        data = {
            "model_id": self.settings.elevenlabs_stt_model,
            "tag_audio_events": "false",
            "diarize": "false",
        }
        if language is not None:
            data["language_code"] = {"kk": "kaz", "ru": "rus", "en": "eng"}.get(language, language)
        try:
            async with httpx.AsyncClient(timeout=self.settings.provider_timeout_seconds) as client:
                response = await client.post(
                    url,
                    headers={"xi-api-key": self._api_key()},
                    data=data,
                    files={"file": (filename, content, content_type)},
                )
        except httpx.HTTPError as exc:
            raise AudioProviderError("ElevenLabs transcription request failed") from exc
        if response.status_code >= 400:
            request_id = response.headers.get("request-id", "unknown")
            raise AudioProviderError(
                f"ElevenLabs transcription returned HTTP {response.status_code} "
                f"(request_id={request_id})"
            )
        text = str(response.json().get("text") or "").strip()
        if not text:
            raise AudioProviderError("ElevenLabs returned an empty transcription")
        return text

    async def synthesize(
        self,
        text: str,
        *,
        voice_id: str | None = None,
        output_format: str | None = None,
    ) -> bytes:
        if not text.strip():
            raise AudioProviderError("Cannot synthesize empty text")
        selected_voice = (voice_id or self._voice_id()).strip()
        audio_chunks: list[bytes] = []
        try:
            async with connect(
                self._dialogue_url(output_format),
                additional_headers={"xi-api-key": self._api_key()},
                open_timeout=self.settings.provider_timeout_seconds,
                close_timeout=10,
                max_size=None,
            ) as websocket:
                await websocket.send(json.dumps({"voices": [selected_voice]}))
                await websocket.send(
                    json.dumps(
                        {
                            "inputs": [
                                {
                                    "text": text,
                                    "voice_id": selected_voice,
                                    "new_turn": True,
                                }
                            ]
                        }
                    )
                )
                await websocket.send(json.dumps({"close_socket": True}))
                while True:
                    event = self._event(await websocket.recv())
                    if event.get("error"):
                        raise AudioProviderError("ElevenLabs speech generation failed")
                    if event.get("audio"):
                        audio_chunks.append(base64.b64decode(str(event["audio"])))
                    if event.get("is_final"):
                        break
        except AudioProviderError:
            raise
        except Exception as exc:
            raise AudioProviderError("ElevenLabs speech request failed") from exc
        audio = b"".join(audio_chunks)
        if not audio:
            raise AudioProviderError("ElevenLabs returned empty audio")
        return audio

    def _dialogue_url(self, output_format: str | None = None) -> str:
        parsed = urlparse(str(self.settings.elevenlabs_base_url))
        scheme = "wss" if parsed.scheme == "https" else "ws"
        base_path = parsed.path.rstrip("/")
        path = f"{base_path}/text-to-dialogue/stream-input"
        query = urlencode(
            {
                "model_id": self.settings.elevenlabs_tts_model,
                "output_format": output_format or self.settings.elevenlabs_output_format,
            }
        )
        return urlunparse((scheme, parsed.netloc, path, "", query, ""))

    @staticmethod
    def _event(message: str | bytes) -> dict[str, Any]:
        payload = json.loads(message)
        if not isinstance(payload, dict):
            raise AudioProviderError("ElevenLabs returned an invalid event")
        return payload
