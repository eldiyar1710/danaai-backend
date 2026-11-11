import asyncio
import hashlib
import math
import re
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import jwt
import structlog
from fastapi import HTTPException, UploadFile, status
from minio import Minio
from minio.error import S3Error
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from urllib3 import BaseHTTPResponse

from app.core.config import Settings
from app.modules.documents.embeddings import embed_dense
from app.modules.documents.models import Document, DocumentStatus
from app.modules.users.models import User, UserRole
from app.modules.videos.media import VIDEO_MIME_BY_SUFFIX, sniff_video
from app.modules.videos.models import SafetyVideo, SafetyVideoDocument, VideoStatus, card_texts
from app.modules.videos.schemas import VideoRead, VideoSuggestion, VideoUpdate
from app.workers.celery_app import celery_app

logger = structlog.get_logger(__name__)

_VIDEO_TOKEN_TYPE = "video"  # noqa: S105 - JWT "type" claim, not a secret
_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")
_CHUNK = 1024 * 1024


def embedding_model_id(settings: Settings) -> str:
    return f"{settings.embedding_provider}:{settings.embedding_model}"


async def embed_card(settings: Settings, video: SafetyVideo) -> list[list[float]]:
    texts = card_texts(video)
    card = await embed_dense(settings, texts[:1], query=False)
    questions = await embed_dense(settings, texts[1:], query=True) if texts[1:] else []
    return [*card, *questions]


def _cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    norm = math.sqrt(sum(a * a for a in left)) * math.sqrt(sum(b * b for b in right))
    return dot / norm if norm else 0.0


class VideoTokens:
    """Short-lived signed URLs so <video src> works without an Authorization header."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def issue(self, video: SafetyVideo, user: User) -> tuple[str, datetime]:
        expires_at = datetime.now(UTC) + timedelta(minutes=self.settings.video_url_ttl_minutes)
        token = jwt.encode(
            {
                "type": _VIDEO_TOKEN_TYPE,
                "sub": str(user.id),
                "vid": str(video.id),
                "org": str(video.organization_id),
                "exp": int(expires_at.timestamp()),
            },
            self.settings.jwt_secret_key.get_secret_value(),
            algorithm=self.settings.jwt_algorithm,
        )
        return token, expires_at

    def verify(self, token: str, video_id: UUID) -> dict[str, Any]:
        try:
            payload: dict[str, Any] = jwt.decode(
                token,
                self.settings.jwt_secret_key.get_secret_value(),
                algorithms=[self.settings.jwt_algorithm],
                options={"require": ["type", "sub", "vid", "org", "exp"]},
            )
        except jwt.PyJWTError as exc:
            raise HTTPException(status_code=401, detail="Invalid or expired video link") from exc
        if payload["type"] != _VIDEO_TOKEN_TYPE or payload["vid"] != str(video_id):
            raise HTTPException(status_code=401, detail="Invalid or expired video link")
        return payload

    def urls(self, video: SafetyVideo, user: User) -> tuple[str, str | None, datetime]:
        token, expires_at = self.issue(video, user)
        base = f"{self.settings.api_v1_prefix}/videos/{video.id}"
        thumbnail = f"{base}/thumbnail?token={token}" if video.thumbnail_path else None
        return f"{base}/stream?token={token}", thumbnail, expires_at


class VideoService:
    def __init__(self, session: AsyncSession, storage: Minio, settings: Settings) -> None:
        self.session = session
        self.storage = storage
        self.settings = settings
        self.tokens = VideoTokens(settings)

    # ------------------------------------------------------------------ helpers
    def tenant(self, actor: User, requested: UUID | None = None) -> UUID:
        if actor.role == UserRole.SUPER_ADMIN:
            if requested is None:
                raise HTTPException(status_code=422, detail="organization_id is required")
            return requested
        if actor.role == UserRole.ORG_ADMIN and actor.organization_id is not None:
            if requested is not None and requested != actor.organization_id:
                raise HTTPException(status_code=403, detail="Cross-tenant access denied")
            return actor.organization_id
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    async def _get_admin(self, actor: User, video_id: UUID) -> SafetyVideo:
        video = await self.session.get(SafetyVideo, video_id)
        if video is None or (
            actor.role != UserRole.SUPER_ADMIN and video.organization_id != actor.organization_id
        ):
            raise HTTPException(status_code=404, detail="Video not found")
        if actor.role not in {UserRole.SUPER_ADMIN, UserRole.ORG_ADMIN}:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return video

    async def linked_document_ids(self, video_id: UUID) -> list[UUID]:
        result = await self.session.execute(
            select(SafetyVideoDocument.document_id).where(SafetyVideoDocument.video_id == video_id)
        )
        return list(result.scalars())

    async def _set_links(self, video: SafetyVideo, document_ids: list[UUID]) -> None:
        unique = list(dict.fromkeys(document_ids))
        if unique:
            result = await self.session.execute(
                select(Document.id).where(
                    Document.id.in_(unique),
                    Document.organization_id == video.organization_id,
                    Document.status != DocumentStatus.ARCHIVED,
                )
            )
            found = set(result.scalars())
            missing = [str(doc_id) for doc_id in unique if doc_id not in found]
            if missing:
                raise HTTPException(
                    status_code=422,
                    detail=f"Unknown or archived documents for this organization: {missing}",
                )
        await self.session.execute(
            delete(SafetyVideoDocument).where(SafetyVideoDocument.video_id == video.id)
        )
        self.session.add_all(
            SafetyVideoDocument(video_id=video.id, document_id=doc_id) for doc_id in unique
        )

    async def read(self, video: SafetyVideo, actor: User) -> VideoRead:
        stream_url = thumbnail_url = None
        if video.status in {VideoStatus.READY, VideoStatus.APPROVED}:
            stream_url, thumbnail_url, _ = self.tokens.urls(video, actor)
        return VideoRead(
            id=video.id,
            organization_id=video.organization_id,
            title=video.title,
            description=video.description,
            example_questions=list(video.example_questions),
            language=video.language,
            linked_document_ids=await self.linked_document_ids(video.id),
            original_filename=video.original_filename,
            mime_type=video.mime_type,
            size_bytes=video.size_bytes,
            duration_seconds=video.duration_seconds,
            width=video.width,
            height=video.height,
            status=video.status.value,
            error_message=video.error_message,
            approved_by_id=video.approved_by_id,
            approved_at=video.approved_at,
            created_at=video.created_at,
            stream_url=stream_url,
            thumbnail_url=thumbnail_url,
        )

    # ------------------------------------------------------------------ admin
    async def upload(
        self,
        actor: User,
        file: UploadFile,
        *,
        title: str,
        description: str,
        example_questions: list[str],
        linked_document_ids: list[UUID],
        language: str,
        organization_id: UUID | None,
    ) -> SafetyVideo:
        tenant_id = self.tenant(actor, organization_id)
        filename = Path(file.filename or "video").name
        suffix = Path(filename).suffix.lower()
        mime_type = VIDEO_MIME_BY_SUFFIX.get(suffix)
        if mime_type is None:
            raise HTTPException(
                status_code=415, detail="Supported video formats: MP4, M4V, MOV, WEBM"
            )
        size, digest, head = await asyncio.to_thread(self._inspect_upload, file)
        if size == 0:
            raise HTTPException(status_code=422, detail="Video file is empty")
        if size > self.settings.max_video_upload_size_bytes:
            raise HTTPException(status_code=413, detail="Video file is too large")
        if not sniff_video(suffix, head):
            raise HTTPException(status_code=422, detail="File content is not a valid video")
        questions = VideoUpdate(example_questions=example_questions).example_questions or []

        video_id = uuid4()
        video = SafetyVideo(
            id=video_id,
            organization_id=tenant_id,
            title=title.strip(),
            description=description.strip(),
            example_questions=questions,
            language=language,
            original_filename=filename,
            mime_type=mime_type,
            size_bytes=size,
            sha256=digest,
            minio_path=f"{tenant_id}/{video_id}/original{suffix}",
            status=VideoStatus.PROCESSING,
            created_by_id=actor.id,
        )
        self.session.add(video)
        await self.session.flush()
        await self._set_links(video, linked_document_ids)
        await asyncio.to_thread(self._put_file, video.minio_path, file, size, mime_type)
        try:
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            await asyncio.to_thread(self._remove, [video.minio_path])
            raise
        celery_app.send_task("videos.process", args=[str(video_id)])
        return video

    async def list(
        self, actor: User, organization_id: UUID | None, status_filter: VideoStatus | None
    ) -> list[SafetyVideo]:
        tenant_id = self.tenant(actor, organization_id)
        query = select(SafetyVideo).where(SafetyVideo.organization_id == tenant_id)
        if status_filter is not None:
            query = query.where(SafetyVideo.status == status_filter)
        result = await self.session.execute(query.order_by(SafetyVideo.created_at.desc()))
        return list(result.scalars())

    async def get(self, actor: User, video_id: UUID) -> SafetyVideo:
        return await self._get_admin(actor, video_id)

    async def update(self, actor: User, video_id: UUID, data: VideoUpdate) -> SafetyVideo:
        video = await self._get_admin(actor, video_id)
        if video.status == VideoStatus.ARCHIVED:
            raise HTTPException(status_code=409, detail="Archived videos cannot be edited")
        card_changed = False
        if data.title is not None:
            video.title, card_changed = data.title.strip(), True
        if data.description is not None:
            video.description, card_changed = data.description.strip(), True
        if data.example_questions is not None:
            video.example_questions, card_changed = data.example_questions, True
        if data.language is not None:
            video.language = data.language
        if data.linked_document_ids is not None:
            if video.status == VideoStatus.APPROVED and not data.linked_document_ids:
                raise HTTPException(
                    status_code=422,
                    detail="An approved video must stay linked to at least one document",
                )
            await self._set_links(video, data.linked_document_ids)
        if card_changed and video.status in {VideoStatus.READY, VideoStatus.APPROVED}:
            video.embeddings = await embed_card(self.settings, video)
            video.embedding_model = embedding_model_id(self.settings)
        await self.session.commit()
        await self.session.refresh(video)
        return video

    async def approve(self, actor: User, video_id: UUID) -> SafetyVideo:
        video = await self._get_admin(actor, video_id)
        if video.status not in {VideoStatus.READY, VideoStatus.APPROVED}:
            raise HTTPException(
                status_code=409, detail=f"Video cannot be approved in status {video.status.value}"
            )
        if not await self.linked_document_ids(video.id):
            raise HTTPException(
                status_code=422,
                detail="Link the video to at least one instruction before approval",
            )
        if not video.embeddings or video.embedding_model != embedding_model_id(self.settings):
            video.embeddings = await embed_card(self.settings, video)
            video.embedding_model = embedding_model_id(self.settings)
        video.status = VideoStatus.APPROVED
        video.approved_by_id = actor.id
        video.approved_at = datetime.now(UTC)
        await self.session.commit()
        await self.session.refresh(video)
        return video

    async def reprocess(self, actor: User, video_id: UUID) -> SafetyVideo:
        """Run media processing again, e.g. after a storage or provider outage."""
        video = await self._get_admin(actor, video_id)
        if video.status not in {VideoStatus.FAILED, VideoStatus.READY}:
            raise HTTPException(
                status_code=409,
                detail=f"Video cannot be reprocessed in status {video.status.value}",
            )
        exists = await asyncio.to_thread(self._object_exists, video.minio_path)
        if not exists:
            raise HTTPException(
                status_code=409,
                detail="The uploaded file is missing from storage; delete and upload again",
            )
        video.status = VideoStatus.PROCESSING
        video.error_message = None
        await self.session.commit()
        await self.session.refresh(video)
        celery_app.send_task("videos.process", args=[str(video.id)])
        return video

    async def archive(self, actor: User, video_id: UUID) -> SafetyVideo:
        video = await self._get_admin(actor, video_id)
        video.status = VideoStatus.ARCHIVED
        await self.session.commit()
        await self.session.refresh(video)
        return video

    async def delete(self, actor: User, video_id: UUID) -> None:
        video = await self._get_admin(actor, video_id)
        paths = [path for path in (video.minio_path, video.thumbnail_path) if path]
        await self.session.delete(video)
        await self.session.commit()
        await asyncio.to_thread(self._remove, paths)

    # ------------------------------------------------------------------ playback
    async def resolve_playback(
        self, video_id: UUID, *, token: str | None, actor: User | None
    ) -> SafetyVideo:
        """Authorize playback by signed link or by bearer token.

        Employees see approved videos of their organization only; admins can also preview
        videos that are processed but not yet approved.
        """
        video = await self.session.get(SafetyVideo, video_id)
        if token is not None:
            claims = self.tokens.verify(token, video_id)
            if video is None or str(video.organization_id) != claims["org"]:
                raise HTTPException(status_code=404, detail="Video not found")
            allowed = {VideoStatus.APPROVED, VideoStatus.READY}
        elif actor is not None:
            if video is None or (
                actor.role != UserRole.SUPER_ADMIN
                and video.organization_id != actor.organization_id
            ):
                raise HTTPException(status_code=404, detail="Video not found")
            is_admin = actor.role in {UserRole.SUPER_ADMIN, UserRole.ORG_ADMIN}
            allowed = (
                {VideoStatus.APPROVED, VideoStatus.READY} if is_admin else {VideoStatus.APPROVED}
            )
        else:
            raise HTTPException(status_code=401, detail="Authentication required")
        if video.status not in allowed:
            raise HTTPException(status_code=404, detail="Video not found")
        return video

    def stat_size(self, path: str) -> int:
        return int(self.storage.stat_object(self.settings.minio_videos_bucket, path).size or 0)

    def open_range(self, path: str, start: int, length: int) -> BaseHTTPResponse:
        return self.storage.get_object(
            self.settings.minio_videos_bucket, path, offset=start, length=length
        )

    @staticmethod
    def parse_range(header: str | None, size: int) -> tuple[int, int] | None:
        """Return an inclusive (start, end) byte range, or None for the whole file."""
        if not header:
            return None
        match = _RANGE.match(header.strip())
        if match is None or (not match.group(1) and not match.group(2)):
            raise HTTPException(
                status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
                headers={"Content-Range": f"bytes */{size}"},
            )
        if match.group(1):
            start = int(match.group(1))
            end = int(match.group(2)) if match.group(2) else size - 1
        else:
            suffix_length = int(match.group(2))
            start, end = max(size - suffix_length, 0), size - 1
        end = min(end, size - 1)
        if start > end or start >= size:
            raise HTTPException(
                status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
                headers={"Content-Range": f"bytes */{size}"},
            )
        return start, end

    # ------------------------------------------------------------------ storage
    def _inspect_upload(self, file: UploadFile) -> tuple[int, str, bytes]:
        stream = file.file
        stream.seek(0)
        digest = hashlib.sha256()
        size = 0
        head = b""
        while chunk := stream.read(_CHUNK):
            if not head:
                head = chunk[:64]
            size += len(chunk)
            if size > self.settings.max_video_upload_size_bytes:
                break
            digest.update(chunk)
        stream.seek(0)
        return size, digest.hexdigest(), head

    def _put_file(self, path: str, file: UploadFile, size: int, mime_type: str) -> None:
        bucket = self.settings.minio_videos_bucket
        if not self.storage.bucket_exists(bucket):
            self.storage.make_bucket(bucket)
        file.file.seek(0)
        self.storage.put_object(bucket, path, file.file, size, content_type=mime_type)

    def _object_exists(self, path: str) -> bool:
        try:
            self.storage.stat_object(self.settings.minio_videos_bucket, path)
        except S3Error as exc:
            if exc.code in {"NoSuchKey", "NoSuchObject", "NoSuchBucket"}:
                return False
            raise
        return True

    def _remove(self, paths: Sequence[str]) -> None:
        for path in paths:
            try:
                self.storage.remove_object(self.settings.minio_videos_bucket, path)
            except Exception:
                logger.warning("video_object_cleanup_failed", path=path)


class VideoMatcher:
    """Pick training videos for an answer that is already grounded in documents."""

    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.tokens = VideoTokens(settings)

    async def suggest(
        self,
        actor: User,
        organization_id: UUID,
        query: str,
        cited_document_ids: list[UUID],
    ) -> list[VideoSuggestion]:
        if not cited_document_ids or self.settings.video_max_suggestions == 0:
            return []
        try:
            return await self._suggest(actor, organization_id, query, cited_document_ids)
        except Exception as exc:
            logger.warning("video_suggestion_failed", error=type(exc).__name__)
            return []

    async def _suggest(
        self,
        actor: User,
        organization_id: UUID,
        query: str,
        cited_document_ids: list[UUID],
    ) -> list[VideoSuggestion]:
        result = await self.session.execute(
            select(SafetyVideo, SafetyVideoDocument.document_id)
            .join(SafetyVideoDocument, SafetyVideoDocument.video_id == SafetyVideo.id)
            .where(
                SafetyVideo.organization_id == organization_id,
                SafetyVideo.status == VideoStatus.APPROVED,
                SafetyVideoDocument.document_id.in_(set(cited_document_ids)),
            )
        )
        candidates: dict[UUID, tuple[SafetyVideo, list[UUID]]] = {}
        for video, document_id in result.all():
            candidates.setdefault(video.id, (video, []))[1].append(document_id)
        model_id = embedding_model_id(self.settings)
        usable = {
            video_id: entry
            for video_id, entry in candidates.items()
            if entry[0].embeddings and entry[0].embedding_model == model_id
        }
        if not usable:
            return []
        query_vector = (await embed_dense(self.settings, [query], query=True))[0]
        scored: list[tuple[float, SafetyVideo, list[UUID]]] = []
        for video, documents in usable.values():
            score = max(_cosine(query_vector, vector) for vector in video.embeddings or [])
            if score >= self.settings.video_match_min_score:
                scored.append((score, video, documents))
        scored.sort(key=lambda item: item[0], reverse=True)
        suggestions = []
        for score, video, documents in scored[: self.settings.video_max_suggestions]:
            stream_url, thumbnail_url, expires_at = self.tokens.urls(video, actor)
            suggestions.append(
                VideoSuggestion(
                    id=video.id,
                    title=video.title,
                    description=video.description,
                    duration_seconds=video.duration_seconds,
                    width=video.width,
                    height=video.height,
                    mime_type=video.mime_type,
                    stream_url=stream_url,
                    thumbnail_url=thumbnail_url,
                    expires_at=expires_at,
                    score=round(score, 4),
                    linked_document_ids=documents,
                )
            )
        return suggestions
