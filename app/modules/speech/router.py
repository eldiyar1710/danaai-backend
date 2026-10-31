from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile

from app.core.config import Settings
from app.core.dependencies import get_app_settings, get_current_user
from app.integrations.voice_audio import VoiceAudioClient
from app.modules.rag.language import Language
from app.modules.speech.schemas import SynthesisRequest, TranscriptionResponse, VoicesResponse
from app.modules.speech.service import SpeechService
from app.modules.users.models import User

router = APIRouter(prefix="/speech", tags=["speech"])


def service(settings: Settings = Depends(get_app_settings)) -> SpeechService:
    return SpeechService(settings, VoiceAudioClient(settings))


@router.post("/transcribe", response_model=TranscriptionResponse)
async def transcribe(
    file: UploadFile = File(...),
    language: Annotated[Language | None, Form()] = None,
    _actor: User = Depends(get_current_user),
    speech: SpeechService = Depends(service),
) -> TranscriptionResponse:
    content = await file.read(speech.settings.max_audio_upload_size_bytes + 1)
    return await speech.transcribe(
        filename=file.filename or "audio",
        content=content,
        declared_mime=file.content_type,
        language=language,
    )


@router.post(
    "/synthesize",
    responses={200: {"content": {"audio/mpeg": {}, "audio/wav": {}}}},
)
async def synthesize(
    data: SynthesisRequest,
    _actor: User = Depends(get_current_user),
    speech: SpeechService = Depends(service),
) -> Response:
    audio = await speech.synthesize(data)
    return Response(
        content=audio.content,
        media_type=audio.content_type,
        headers={
            "Content-Disposition": f'inline; filename="speech.{audio.extension}"',
            "X-AI-Generated-Voice": "true",
            "X-Audio-Provider": audio.provider,
            "X-Audio-Model": audio.model,
            "X-Voice-ID": audio.voice,
        },
    )


@router.get("/voices", response_model=VoicesResponse)
async def voices(
    _actor: User = Depends(get_current_user),
    speech: SpeechService = Depends(service),
) -> VoicesResponse:
    default_voice = (
        speech.settings.elevenlabs_voice_id
        if speech.settings.tts_provider == "elevenlabs" and speech.settings.elevenlabs_voice_id
        else speech.settings.tts_voice
    )
    return VoicesResponse(default_voice_id=default_voice, voices=speech.voices())
