import asyncio
import tempfile
from pathlib import Path
from typing import Any
from uuid import UUID

import structlog

import app.models  # noqa: F401
from app.core.config import Settings, get_settings
from app.core.database import create_engine, create_session_factory
from app.integrations.minio_client import create_minio_client
from app.modules.videos.media import (
    VideoMediaError,
    make_faststart,
    make_thumbnail,
    probe,
)
from app.modules.videos.models import SafetyVideo, VideoStatus
from app.modules.videos.service import embed_card, embedding_model_id
from app.workers.celery_app import celery_app

logger = structlog.get_logger(__name__)
_MAX_RETRIES = 3


@celery_app.task(  # type: ignore[untyped-decorator]
    name="videos.process",
    bind=True,
    acks_late=True,
    max_retries=_MAX_RETRIES,
)
def process_video(self: Any, video_id: str) -> None:
    try:
        asyncio.run(_process(UUID(video_id)))
    except VideoMediaError as exc:
        asyncio.run(_fail(UUID(video_id), str(exc)))
    except Exception as exc:
        # Keep the real cause (S3 code, provider error) so admins can act on it.
        message = f"{type(exc).__name__}: {exc}"
        logger.exception(
            "video_processing_attempt_failed",
            video_id=video_id,
            attempt=self.request.retries + 1,
            error=message[:500],
        )
        if self.request.retries >= _MAX_RETRIES:
            asyncio.run(_fail(UUID(video_id), f"Processing failed: {message}"))
            raise
        raise self.retry(exc=exc, countdown=min(60, 5 * 2**self.request.retries)) from exc


async def _fail(video_id: UUID, message: str) -> None:
    settings = get_settings()
    engine = create_engine(settings)
    try:
        async with create_session_factory(engine)() as session:
            video = await session.get(SafetyVideo, video_id)
            if video is not None and video.status == VideoStatus.PROCESSING:
                video.status = VideoStatus.FAILED
                video.error_message = message[:2000]
                await session.commit()
        logger.warning("video_processing_failed", video_id=str(video_id), error=message)
    finally:
        await engine.dispose()


async def _process(video_id: UUID) -> None:
    settings = get_settings()
    engine = create_engine(settings)
    storage = create_minio_client(settings)
    try:
        async with create_session_factory(engine)() as session:
            video = await session.get(SafetyVideo, video_id)
            if video is None or video.status != VideoStatus.PROCESSING:
                return
            with tempfile.TemporaryDirectory(prefix="semyzbay-video-") as workdir:
                replaced = await asyncio.to_thread(
                    _process_media, settings, storage, video, Path(workdir)
                )
            video.embeddings = await embed_card(settings, video)
            video.embedding_model = embedding_model_id(settings)
            video.status = VideoStatus.READY
            video.error_message = None
            await session.commit()
            # The original is removed only after the new path is committed, so a failure at
            # any earlier step leaves it in place and a retry starts from a complete state.
            if replaced is not None:
                await asyncio.to_thread(_remove_quietly, settings, storage, replaced)
            logger.info("video_processed", video_id=str(video_id))
    finally:
        await engine.dispose()


def _remove_quietly(settings: Settings, storage: Any, path: str) -> None:
    try:
        storage.remove_object(settings.minio_videos_bucket, path)
    except Exception as exc:
        logger.warning("video_original_cleanup_failed", path=path, error=str(exc)[:200])


def _process_media(
    settings: Settings, storage: Any, video: SafetyVideo, workdir: Path
) -> str | None:
    """Probe, remux and thumbnail the video; return the replaced object path, if any.

    Nothing is deleted here: the caller removes the replaced original after committing.
    """
    bucket = settings.minio_videos_bucket
    suffix = Path(video.minio_path).suffix
    source = workdir / f"source{suffix}"
    storage.fget_object(bucket, video.minio_path, str(source))
    info = probe(source)
    if info.duration_seconds > settings.max_video_duration_seconds:
        raise VideoMediaError(f"Video is longer than {settings.max_video_duration_seconds} seconds")
    video.duration_seconds = info.duration_seconds
    video.width = info.width
    video.height = info.height

    replaced: str | None = None
    playable = source
    if suffix in {".mp4", ".m4v", ".mov"}:
        faststart = workdir / "playback.mp4"
        playback_path = f"{video.organization_id}/{video.id}/playback.mp4"
        if playback_path != video.minio_path and make_faststart(source, faststart):
            storage.fput_object(bucket, playback_path, str(faststart), content_type="video/mp4")
            replaced = video.minio_path
            playable = faststart
            video.minio_path = playback_path
            video.mime_type = "video/mp4"
            video.size_bytes = faststart.stat().st_size

    thumbnail = workdir / "thumbnail.jpg"
    if make_thumbnail(playable, thumbnail, info.duration_seconds):
        thumbnail_path = f"{video.organization_id}/{video.id}/thumbnail.jpg"
        storage.fput_object(bucket, thumbnail_path, str(thumbnail), content_type="image/jpeg")
        video.thumbnail_path = thumbnail_path
    return replaced
