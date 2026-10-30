import asyncio
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, select

import app.models  # noqa: F401
from app.core.config import get_settings
from app.core.database import create_engine, create_session_factory
from app.integrations.minio_client import create_minio_client
from app.integrations.qdrant_client import create_qdrant_client
from app.modules.documents.chunker import chunk_blocks
from app.modules.documents.indexer import DocumentIndexer, delete_document_points
from app.modules.documents.models import (
    Document,
    DocumentChunk,
    DocumentStatus,
    DocumentVersion,
    JobStatus,
    ProcessingJob,
    ProcessingStatus,
)
from app.modules.documents.parser import parse_document
from app.workers.celery_app import celery_app


@celery_app.task(  # type: ignore[untyped-decorator]
    name="documents.process",
    acks_late=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
    max_retries=3,
)
def process_document(document_id: str, version_id: str, job_id: str) -> None:
    asyncio.run(_process(UUID(document_id), UUID(version_id), UUID(job_id)))


async def _process(document_id: UUID, version_id: UUID, job_id: UUID) -> None:
    settings = get_settings()
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            job = await session.get(ProcessingJob, job_id)
            version = await session.get(DocumentVersion, version_id)
            document = await session.get(Document, document_id)
            if document is None:
                await _remove_qdrant_document(document_id)
                return
            if job is None or version is None:
                return
            if job.status == JobStatus.SUCCEEDED:
                return
            if document.status == DocumentStatus.ARCHIVED:
                job.status = JobStatus.CANCELLED
                job.completed_at = datetime.now(UTC)
                await session.commit()
                return
            job.status, job.progress = JobStatus.RUNNING, 10
            version.processing_status = ProcessingStatus.RUNNING
            document.status = DocumentStatus.PROCESSING
            await session.commit()
            try:
                storage = create_minio_client(settings)
                response = await asyncio.to_thread(
                    storage.get_object, settings.minio_documents_bucket, version.minio_path
                )
                try:
                    content = await asyncio.to_thread(response.read)
                finally:
                    response.close()
                    response.release_conn()
                blocks = await asyncio.to_thread(parse_document, version.original_filename, content)
                chunks = chunk_blocks(
                    blocks,
                    chunk_size=settings.document_chunk_size,
                    chunk_overlap=settings.document_chunk_overlap,
                )
                job.progress = 40
                await session.commit()
                await session.refresh(document)
                if document.status == DocumentStatus.ARCHIVED:
                    job.status = JobStatus.CANCELLED
                    job.completed_at = datetime.now(UTC)
                    await session.commit()
                    return
                qdrant = create_qdrant_client(settings)
                try:
                    point_ids = await DocumentIndexer(settings, qdrant).replace_version(
                        document,
                        version.id,
                        chunks,
                        active=document.active_version_id == version.id,
                    )
                finally:
                    await qdrant.close()
                current_document = await session.scalar(
                    select(Document)
                    .where(Document.id == document_id)
                    .execution_options(populate_existing=True)
                )
                if current_document is None or current_document.status == DocumentStatus.ARCHIVED:
                    await _remove_qdrant_document(document_id)
                    if current_document is not None:
                        job.status = JobStatus.CANCELLED
                        job.completed_at = datetime.now(UTC)
                        await session.commit()
                    return
                await session.execute(
                    delete(DocumentChunk).where(DocumentChunk.document_version_id == version.id)
                )
                session.add_all(
                    DocumentChunk(
                        id=point_id,
                        organization_id=document.organization_id,
                        document_id=document.id,
                        document_version_id=version.id,
                        qdrant_point_id=point_id,
                        chunk_index=chunk.index,
                        text=chunk.text,
                        page_number=chunk.page_number,
                        section_title=chunk.section_title,
                        section_number=chunk.section_number,
                    )
                    for point_id, chunk in zip(point_ids, chunks, strict=True)
                )
                job.status, job.progress = JobStatus.SUCCEEDED, 100
                job.completed_at = datetime.now(UTC)
                version.processing_status = ProcessingStatus.SUCCEEDED
                document.status = DocumentStatus.READY
                await session.commit()
            except Exception as exc:
                await session.rollback()
                job = await session.scalar(select(ProcessingJob).where(ProcessingJob.id == job_id))
                version = await session.get(DocumentVersion, version_id)
                document = await session.get(Document, document_id)
                if job and version and document:
                    job.status = JobStatus.FAILED
                    job.error_message = type(exc).__name__
                    job.completed_at = datetime.now(UTC)
                    version.processing_status = ProcessingStatus.FAILED
                    document.status = (
                        DocumentStatus.READY
                        if document.active_version_id is not None
                        else DocumentStatus.FAILED
                    )
                    await session.commit()
                raise
    finally:
        await engine.dispose()


async def _remove_qdrant_document(document_id: UUID) -> None:
    settings = get_settings()
    qdrant = create_qdrant_client(settings)
    try:
        await delete_document_points(qdrant, settings, document_id)
    finally:
        await qdrant.close()
