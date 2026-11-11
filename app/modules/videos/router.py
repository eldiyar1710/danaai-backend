import asyncio
from collections.abc import Iterator
from typing import cast
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials
from minio import Minio
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.dependencies import (
    bearer,
    get_app_settings,
    get_current_user,
    get_db_session,
    require_roles,
)
from app.modules.users.models import User, UserRole
from app.modules.videos.models import VideoStatus
from app.modules.videos.schemas import VideoRead, VideoUpdate
from app.modules.videos.service import VideoService

router = APIRouter(prefix="/videos", tags=["videos"])
admin = require_roles(UserRole.SUPER_ADMIN, UserRole.ORG_ADMIN)


def service(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_app_settings),
) -> VideoService:
    return VideoService(session, cast(Minio, request.app.state.minio), settings)


@router.post("", response_model=VideoRead, status_code=status.HTTP_201_CREATED)
async def upload_video(
    file: UploadFile = File(..., description="MP4, M4V, MOV or WEBM"),
    title: str = Form(..., min_length=2, max_length=500),
    description: str = Form("", max_length=5000),
    example_questions: list[str] = Form(
        default=[], description="Repeat the field for each question the video answers"
    ),
    linked_document_ids: list[UUID] = Form(
        default=[], description="Repeat the field for each instruction the video illustrates"
    ),
    language: str = Form("ru", pattern="^(kk|ru|en)$"),
    organization_id: UUID | None = Form(None),
    actor: User = Depends(admin),
    videos: VideoService = Depends(service),
) -> VideoRead:
    video = await videos.upload(
        actor,
        file,
        title=title,
        description=description,
        example_questions=example_questions,
        linked_document_ids=linked_document_ids,
        language=language,
        organization_id=organization_id,
    )
    return await videos.read(video, actor)


@router.get("", response_model=list[VideoRead])
async def list_videos(
    organization_id: UUID | None = None,
    status_filter: VideoStatus | None = Query(default=None, alias="status"),
    actor: User = Depends(admin),
    videos: VideoService = Depends(service),
) -> list[VideoRead]:
    return [
        await videos.read(video, actor)
        for video in await videos.list(actor, organization_id, status_filter)
    ]


@router.get("/{video_id}", response_model=VideoRead)
async def get_video(
    video_id: UUID, actor: User = Depends(admin), videos: VideoService = Depends(service)
) -> VideoRead:
    return await videos.read(await videos.get(actor, video_id), actor)


@router.patch("/{video_id}", response_model=VideoRead)
async def update_video(
    video_id: UUID,
    data: VideoUpdate,
    actor: User = Depends(admin),
    videos: VideoService = Depends(service),
) -> VideoRead:
    return await videos.read(await videos.update(actor, video_id, data), actor)


@router.post("/{video_id}/approve", response_model=VideoRead)
async def approve_video(
    video_id: UUID, actor: User = Depends(admin), videos: VideoService = Depends(service)
) -> VideoRead:
    return await videos.read(await videos.approve(actor, video_id), actor)


@router.post("/{video_id}/reprocess", response_model=VideoRead)
async def reprocess_video(
    video_id: UUID, actor: User = Depends(admin), videos: VideoService = Depends(service)
) -> VideoRead:
    return await videos.read(await videos.reprocess(actor, video_id), actor)


@router.post("/{video_id}/archive", response_model=VideoRead)
async def archive_video(
    video_id: UUID, actor: User = Depends(admin), videos: VideoService = Depends(service)
) -> VideoRead:
    return await videos.read(await videos.archive(actor, video_id), actor)


@router.delete("/{video_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_video(
    video_id: UUID, actor: User = Depends(admin), videos: VideoService = Depends(service)
) -> Response:
    await videos.delete(actor, video_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    settings: Settings = Depends(get_app_settings),
    session: AsyncSession = Depends(get_db_session),
) -> User | None:
    if credentials is None:
        return None
    return await get_current_user(credentials, settings, session)


def _stream_object(videos: VideoService, path: str, start: int, length: int) -> Iterator[bytes]:
    response = videos.open_range(path, start, length)
    try:
        yield from response.stream(amt=256 * 1024)
    finally:
        response.close()
        response.release_conn()


@router.get(
    "/{video_id}/stream",
    response_class=StreamingResponse,
    summary="Play a video (supports HTTP Range for seeking)",
    description=(
        "Use the signed `stream_url` from a chat answer or video card directly in "
        "`<video src>`; a bearer token works too."
    ),
)
async def stream_video(
    video_id: UUID,
    request: Request,
    token: str | None = Query(default=None, description="Signed link token"),
    actor: User | None = Depends(_optional_user),
    videos: VideoService = Depends(service),
) -> StreamingResponse:
    video = await videos.resolve_playback(video_id, token=token, actor=actor)
    size = await asyncio.to_thread(videos.stat_size, video.minio_path)
    byte_range = videos.parse_range(request.headers.get("range"), size)
    start, end = byte_range if byte_range else (0, size - 1)
    length = end - start + 1
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(length),
        "Cache-Control": "private, max-age=300",
        "Content-Disposition": "inline",
    }
    if byte_range:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    return StreamingResponse(
        _stream_object(videos, video.minio_path, start, length),
        status_code=status.HTTP_206_PARTIAL_CONTENT if byte_range else status.HTTP_200_OK,
        media_type=video.mime_type,
        headers=headers,
    )


@router.get("/{video_id}/thumbnail", response_class=StreamingResponse)
async def video_thumbnail(
    video_id: UUID,
    token: str | None = Query(default=None, description="Signed link token"),
    actor: User | None = Depends(_optional_user),
    videos: VideoService = Depends(service),
) -> StreamingResponse:
    video = await videos.resolve_playback(video_id, token=token, actor=actor)
    if not video.thumbnail_path:
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    path = video.thumbnail_path
    size = await asyncio.to_thread(videos.stat_size, path)
    return StreamingResponse(
        _stream_object(videos, path, 0, size),
        media_type="image/jpeg",
        headers={"Content-Length": str(size), "Cache-Control": "private, max-age=300"},
    )
