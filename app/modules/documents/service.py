import asyncio
from contextlib import suppress
from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import HTTPException, UploadFile
from minio import Minio
from minio.deleteobjects import DeleteObject
from urllib3.response import BaseHTTPResponse

from app.core.config import Settings
from app.integrations.qdrant_client import create_qdrant_client
from app.modules.documents.indexer import delete_document_points, set_version_active
from app.modules.documents.models import (
    ApprovalStatus,
    Document,
    DocumentStatus,
    DocumentVersion,
    JobStatus,
    ProcessingJob,
    ProcessingStatus,
)
from app.modules.documents.repository import DocumentRepository
from app.modules.documents.schemas import DocumentStatusRead
from app.modules.documents.validation import validate_document
from app.modules.users.models import User, UserRole
from app.workers.celery_app import celery_app


class DocumentService:
    def __init__(self, repository: DocumentRepository, storage: Minio, settings: Settings) -> None:
        self.repository = repository
        self.storage = storage
        self.settings = settings

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

    async def upload(
        self,
        actor: User,
        file: UploadFile,
        title: str,
        language: str,
        organization_id: UUID | None,
    ) -> Document:
        tenant_id = self.tenant(actor, organization_id)
        filename, mime_type, content = await self._read_upload(file)
        document_id, version_id = uuid4(), uuid4()
        object_path = f"{tenant_id}/{document_id}/{version_id}/{filename}"
        bucket = self.settings.minio_documents_bucket
        await self._put(bucket, object_path, content, mime_type)
        document = Document(
            id=document_id,
            organization_id=tenant_id,
            uploaded_by=actor.id,
            title=title,
            original_filename=filename,
            minio_path=object_path,
            mime_type=mime_type,
            size_bytes=len(content),
            language=language,
            status=DocumentStatus.UPLOADED,
            approval_status=ApprovalStatus.PENDING,
            active_version_id=None,
        )
        version = DocumentVersion(
            id=version_id,
            document_id=document_id,
            version_number=1,
            minio_path=object_path,
            original_filename=filename,
            mime_type=mime_type,
            size_bytes=len(content),
            language=language,
            checksum=sha256(content).hexdigest(),
            effective_from=None,
            effective_until=None,
            approved_by=None,
            approved_at=None,
            processing_status=ProcessingStatus.PENDING,
        )
        job = ProcessingJob(
            organization_id=tenant_id,
            resource_id=document_id,
            job_type="document_processing",
            status=JobStatus.PENDING,
            progress=0,
            error_message=None,
            completed_at=None,
        )
        try:
            await self.repository.add(document, version, job)
            await self.repository.session.commit()
        except Exception:
            await self.repository.session.rollback()
            await asyncio.to_thread(self.storage.remove_object, bucket, object_path)
            raise
        celery_app.send_task(
            "documents.process", args=[str(document_id), str(version_id), str(job.id)]
        )
        return document

    async def upload_version(
        self,
        actor: User,
        document_id: UUID,
        file: UploadFile,
        language: str | None,
    ) -> DocumentVersion:
        tenant_id = None if actor.role == UserRole.SUPER_ADMIN else actor.organization_id
        document = await self.repository.get_for_update(document_id, tenant_id)
        if document is None:
            raise HTTPException(status_code=404, detail="Document not found")
        if document.status == DocumentStatus.ARCHIVED:
            raise HTTPException(status_code=409, detail="Archived document cannot be versioned")
        filename, mime_type, content = await self._read_upload(file)
        checksum = sha256(content).hexdigest()
        latest = await self.repository.latest_version(document.id)
        if latest is not None and latest.checksum == checksum:
            raise HTTPException(status_code=409, detail="This file version already exists")
        version = DocumentVersion(
            id=uuid4(),
            document_id=document.id,
            version_number=await self.repository.next_version_number(document.id),
            minio_path="",
            original_filename=filename,
            mime_type=mime_type,
            size_bytes=len(content),
            language=language or document.language,
            checksum=checksum,
            effective_from=None,
            effective_until=None,
            approved_by=None,
            approved_at=None,
            processing_status=ProcessingStatus.PENDING,
        )
        version.minio_path = f"{document.organization_id}/{document.id}/{version.id}/{filename}"
        await self._put(
            self.settings.minio_documents_bucket,
            version.minio_path,
            content,
            mime_type,
        )
        job = ProcessingJob(
            organization_id=document.organization_id,
            resource_id=document.id,
            job_type="document_version_processing",
            status=JobStatus.PENDING,
            progress=0,
            error_message=None,
            completed_at=None,
        )
        try:
            self.repository.session.add_all((version, job))
            await self.repository.session.commit()
        except Exception:
            await self.repository.session.rollback()
            await asyncio.to_thread(
                self.storage.remove_object,
                self.settings.minio_documents_bucket,
                version.minio_path,
            )
            raise
        celery_app.send_task(
            "documents.process", args=[str(document.id), str(version.id), str(job.id)]
        )
        return version

    async def list(self, actor: User, organization_id: UUID | None) -> list[Document]:
        tenant_id = organization_id if actor.role == UserRole.SUPER_ADMIN else actor.organization_id
        if actor.role != UserRole.SUPER_ADMIN and tenant_id is None:
            raise HTTPException(status_code=403, detail="Tenant membership required")
        return await self.repository.list(tenant_id)

    async def get(self, actor: User, document_id: UUID) -> Document:
        tenant_id = None if actor.role == UserRole.SUPER_ADMIN else actor.organization_id
        document = await self.repository.get(document_id, tenant_id)
        if document is None:
            raise HTTPException(status_code=404, detail="Document not found")
        return document

    async def status(self, actor: User, document_id: UUID) -> DocumentStatusRead:
        document = await self.get(actor, document_id)
        return DocumentStatusRead(
            document=document, latest_job=await self.repository.latest_job(document.id)
        )

    async def approve(self, actor: User, document_id: UUID) -> Document:
        tenant_id = None if actor.role == UserRole.SUPER_ADMIN else actor.organization_id
        document = await self.repository.get_for_update(document_id, tenant_id)
        if document is None:
            raise HTTPException(status_code=404, detail="Document not found")
        if document.status == DocumentStatus.ARCHIVED:
            raise HTTPException(status_code=409, detail="Archived document cannot be approved")
        version = await self.repository.latest_version(document.id)
        if version is None or version.processing_status != ProcessingStatus.SUCCEEDED:
            raise HTTPException(status_code=409, detail="Document processing is not complete")
        if document.active_version_id == version.id:
            return document
        now = datetime.now(UTC)
        previous_version_id = document.active_version_id
        previous_metadata = (
            document.minio_path,
            document.original_filename,
            document.mime_type,
            document.size_bytes,
            document.language,
        )
        version.approved_by, version.approved_at = actor.id, now
        version.effective_from = now
        document.active_version_id = version.id
        document.minio_path = version.minio_path
        document.original_filename = version.original_filename
        document.mime_type = version.mime_type
        document.size_bytes = version.size_bytes
        document.language = version.language
        document.approval_status = ApprovalStatus.APPROVED
        document.status = DocumentStatus.READY
        await self.repository.session.commit()
        qdrant = create_qdrant_client(self.settings)
        try:
            await set_version_active(qdrant, self.settings, version.id, active=True)
            if previous_version_id and previous_version_id != version.id:
                await set_version_active(qdrant, self.settings, previous_version_id, active=False)
                previous = await self.repository.session.get(DocumentVersion, previous_version_id)
                if previous is not None:
                    previous.effective_until = now
                    await self.repository.session.commit()
        except Exception as exc:
            with suppress(Exception):
                await set_version_active(qdrant, self.settings, version.id, active=False)
                if previous_version_id is not None:
                    await set_version_active(
                        qdrant, self.settings, previous_version_id, active=True
                    )
            document.active_version_id = previous_version_id
            (
                document.minio_path,
                document.original_filename,
                document.mime_type,
                document.size_bytes,
                document.language,
            ) = previous_metadata
            document.approval_status = (
                ApprovalStatus.APPROVED
                if previous_version_id is not None
                else ApprovalStatus.PENDING
            )
            document.status = (
                DocumentStatus.READY if previous_version_id is not None else DocumentStatus.UPLOADED
            )
            version.approved_by = None
            version.approved_at = None
            version.effective_from = None
            await self.repository.session.commit()
            raise HTTPException(status_code=503, detail="Vector activation failed") from exc
        finally:
            await qdrant.close()
        await self.repository.session.refresh(document)
        return document

    async def archive(self, actor: User, document_id: UUID) -> Document:
        tenant_id = None if actor.role == UserRole.SUPER_ADMIN else actor.organization_id
        document = await self.repository.get_for_update(document_id, tenant_id)
        if document is None:
            raise HTTPException(status_code=404, detail="Document not found")
        if document.active_version_id is not None:
            qdrant = create_qdrant_client(self.settings)
            try:
                await set_version_active(
                    qdrant, self.settings, document.active_version_id, active=False
                )
            finally:
                await qdrant.close()
        document.status = DocumentStatus.ARCHIVED
        document.approval_status = ApprovalStatus.ARCHIVED
        await self.repository.session.commit()
        await self.repository.session.refresh(document)
        return document

    async def reindex(self, actor: User, document_id: UUID) -> DocumentStatusRead:
        document = await self.get(actor, document_id)
        if document.status == DocumentStatus.ARCHIVED:
            raise HTTPException(status_code=409, detail="Archived document cannot be reindexed")
        version = await self.repository.latest_version(document.id)
        if version is None:
            raise HTTPException(status_code=409, detail="Document has no version")
        job = ProcessingJob(
            organization_id=document.organization_id,
            resource_id=document.id,
            job_type="document_reindex",
            status=JobStatus.PENDING,
            progress=0,
            error_message=None,
            completed_at=None,
        )
        self.repository.session.add(job)
        version.processing_status = ProcessingStatus.PENDING
        document.status = (
            DocumentStatus.READY
            if document.active_version_id is not None
            else DocumentStatus.UPLOADED
        )
        await self.repository.session.commit()
        await self.repository.session.refresh(document)
        await self.repository.session.refresh(job)
        response = DocumentStatusRead(document=document, latest_job=job)
        celery_app.send_task(
            "documents.process", args=[str(document.id), str(version.id), str(job.id)]
        )
        return response

    async def download(self, actor: User, document_id: UUID) -> tuple[Document, BaseHTTPResponse]:
        document = await self.get(actor, document_id)
        response = await asyncio.to_thread(
            self.storage.get_object,
            self.settings.minio_documents_bucket,
            document.minio_path,
        )
        return document, response

    async def delete(self, actor: User, document_id: UUID) -> None:
        tenant_id = None if actor.role == UserRole.SUPER_ADMIN else actor.organization_id
        document = await self.repository.get_for_update(document_id, tenant_id)
        if document is None:
            raise HTTPException(status_code=404, detail="Document not found")
        versions = await self.repository.versions(document.id)
        document.status = DocumentStatus.ARCHIVED
        document.approval_status = ApprovalStatus.ARCHIVED
        await self.repository.session.commit()

        qdrant = create_qdrant_client(self.settings)
        try:
            await delete_document_points(qdrant, self.settings, document.id)
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Qdrant deletion failed") from exc
        finally:
            await qdrant.close()

        try:
            await asyncio.to_thread(
                self._remove_objects, {version.minio_path for version in versions}
            )
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Object storage deletion failed") from exc

        document.active_version_id = None
        await self.repository.session.flush()
        await self.repository.delete_jobs(document.id)
        await self.repository.session.delete(document)
        await self.repository.session.commit()

    async def _read_upload(self, file: UploadFile) -> tuple[str, str, bytes]:
        content = await file.read(self.settings.max_upload_size_bytes + 1)
        if not content:
            raise HTTPException(status_code=422, detail="File is empty")
        if len(content) > self.settings.max_upload_size_bytes:
            raise HTTPException(status_code=413, detail="File exceeds upload size limit")
        filename = Path(file.filename or "document").name
        mime_type = validate_document(filename, content, file.content_type)
        return filename, mime_type, content

    def _remove_objects(self, paths: set[str]) -> None:
        errors = list(
            self.storage.remove_objects(
                self.settings.minio_documents_bucket,
                [DeleteObject(path) for path in sorted(paths)],
            )
        )
        if errors:
            raise RuntimeError(f"Failed to remove {len(errors)} object(s)")

    async def _put(self, bucket: str, path: str, content: bytes, mime_type: str) -> None:
        def operation() -> None:
            if not self.storage.bucket_exists(bucket):
                self.storage.make_bucket(bucket)
            self.storage.put_object(
                bucket, path, BytesIO(content), len(content), content_type=mime_type
            )

        await asyncio.to_thread(operation)
