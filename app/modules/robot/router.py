import asyncio
import hmac
import time
from collections import deque
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile

from app.core.config import Settings, get_settings
from app.modules.robot.schemas import RobotReply, TextQuestion
from app.modules.robot.service import RobotService

_request_times: deque[float] = deque()
_rate_lock = asyncio.Lock()
_inference_slots = asyncio.Semaphore(2)


async def require_robot_key(
    x_api_key: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    configured = settings.robot_api_key.get_secret_value() if settings.robot_api_key else ""
    if not configured:
        raise HTTPException(status_code=503, detail="Robot API key is not configured")
    if not x_api_key or not hmac.compare_digest(x_api_key, configured):
        raise HTTPException(status_code=401, detail="Invalid robot API key")
    async with _rate_lock:
        now = time.monotonic()
        while _request_times and _request_times[0] <= now - 60:
            _request_times.popleft()
        if len(_request_times) >= settings.robot_requests_per_minute:
            raise HTTPException(status_code=429, detail="Robot request limit exceeded")
        _request_times.append(now)


router = APIRouter(prefix="/robot", tags=["robot"], dependencies=[Depends(require_robot_key)])


def get_robot_service(settings: Settings = Depends(get_settings)) -> RobotService:
    try:
        return RobotService(settings)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="Robot approvals are invalid") from exc


@router.post("/text", response_model=RobotReply)
async def ask_text(
    data: TextQuestion,
    robot: RobotService = Depends(get_robot_service),
) -> RobotReply:
    async with _inference_slots:
        return await robot.answer_text(data.question, data.language)


@router.post("/audio", response_model=RobotReply)
async def ask_audio(
    file: UploadFile = File(...),
    language: Literal["kk", "ru", "en"] | None = Form(None),
    robot: RobotService = Depends(get_robot_service),
) -> RobotReply:
    content = await file.read(robot.settings.max_audio_upload_size_bytes + 1)
    async with _inference_slots:
        return await robot.answer_audio(
            filename=file.filename or "audio.wav",
            content=content,
            declared_mime=file.content_type,
            language=language,
        )
