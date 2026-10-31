import base64
import json
import wave
from io import BytesIO
from typing import Any
from urllib.parse import urlencode, urlparse, urlunparse
from uuid import uuid4

import httpx
from websockets.asyncio.client import connect

from app.core.config import Settings


class AudioProviderError(RuntimeError):
    pass


class OpenAIAudioClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _api_key(self) -> str:
        if self.settings.openai_api_key is None:
            raise AudioProviderError("OPENAI_API_KEY is not configured")
        value = self.settings.openai_api_key.get_secret_value().strip()
        if not value:
            raise AudioProviderError("OPENAI_API_KEY is not configured")
        return value

    async def transcribe(
        self,
        *,
        filename: str,
        content: bytes,
        content_type: str,
        language: str | None = None,
    ) -> str:
        url = f"{str(self.settings.openai_base_url).rstrip('/')}/audio/transcriptions"
        data = {"model": self.settings.stt_model, "response_format": "json"}
        if language is not None:
            data["language"] = language
        try:
            async with httpx.AsyncClient(timeout=self.settings.provider_timeout_seconds) as client:
                response = await client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {self._api_key()}",
                        "X-Client-Request-Id": str(uuid4()),
                    },
                    data=data,
                    files={"file": (filename, content, content_type)},
                )
        except httpx.HTTPError as exc:
            raise AudioProviderError("OpenAI transcription request failed") from exc
        if response.status_code >= 400:
            request_id = response.headers.get("x-request-id", "unknown")
            raise AudioProviderError(
                f"OpenAI transcription returned HTTP {response.status_code} "
                f"(request_id={request_id})"
            )
        text = str(response.json().get("text") or "").strip()
        if not text:
            raise AudioProviderError("OpenAI returned an empty transcription")
        return text

    async def synthesize(
        self, text: str, *, voice: str | None = None, speed: float | None = None
    ) -> bytes:
        if not text.strip():
            raise AudioProviderError("Cannot synthesize empty text")
        pcm_chunks: list[bytes] = []
        url = self._realtime_url()
        try:
            async with connect(
                url,
                additional_headers={"Authorization": f"Bearer {self._api_key()}"},
                open_timeout=self.settings.provider_timeout_seconds,
                close_timeout=10,
                max_size=None,
            ) as websocket:
                await websocket.send(
                    json.dumps(
                        {
                            "type": "session.update",
                            "session": {
                                "type": "realtime",
                                "model": self.settings.tts_model,
                                "instructions": (
                                    "Read the supplied text aloud exactly as written. "
                                    "Do not add, remove, translate, summarize, or comment on it."
                                ),
                                "output_modalities": ["audio"],
                                "audio": {
                                    "output": {
                                        "format": {"type": "audio/pcm", "rate": 24000},
                                        "voice": voice or self.settings.tts_voice,
                                        "speed": speed or self.settings.tts_speed,
                                    }
                                },
                            },
                        }
                    )
                )
                await websocket.send(
                    json.dumps(
                        {
                            "type": "conversation.item.create",
                            "item": {
                                "type": "message",
                                "role": "user",
                                "content": [{"type": "input_text", "text": text}],
                            },
                        }
                    )
                )
                await websocket.send(
                    json.dumps(
                        {
                            "type": "response.create",
                            "response": {"output_modalities": ["audio"]},
                        }
                    )
                )
                while True:
                    event = self._event(await websocket.recv())
                    event_type = event.get("type")
                    if event_type == "response.output_audio.delta":
                        pcm_chunks.append(base64.b64decode(str(event.get("delta") or "")))
                    elif event_type == "error":
                        error = event.get("error") or {}
                        raise AudioProviderError(
                            f"OpenAI Realtime error: {error.get('code', 'unknown')}"
                        )
                    elif event_type == "response.done":
                        response = event.get("response") or {}
                        if response.get("status") != "completed":
                            raise AudioProviderError("OpenAI audio response was not completed")
                        break
        except AudioProviderError:
            raise
        except Exception as exc:
            raise AudioProviderError("OpenAI Realtime speech request failed") from exc
        pcm = b"".join(pcm_chunks)
        if not pcm:
            raise AudioProviderError("OpenAI returned empty audio")
        return self._pcm_to_wav(pcm)

    def _realtime_url(self) -> str:
        parsed = urlparse(str(self.settings.openai_base_url))
        scheme = "wss" if parsed.scheme == "https" else "ws"
        path = f"{parsed.path.rstrip('/')}/realtime"
        return urlunparse(
            (scheme, parsed.netloc, path, "", urlencode({"model": self.settings.tts_model}), "")
        )

    @staticmethod
    def _event(message: str | bytes) -> dict[str, Any]:
        payload = json.loads(message)
        if not isinstance(payload, dict):
            raise AudioProviderError("OpenAI returned an invalid Realtime event")
        return payload

    @staticmethod
    def _pcm_to_wav(pcm: bytes) -> bytes:
        output = BytesIO()
        with wave.open(output, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(24000)
            wav.writeframes(pcm)
        return output.getvalue()
