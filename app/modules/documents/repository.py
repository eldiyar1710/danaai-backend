import builtins
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.documents.models import Document, DocumentVersion, ProcessingJob


class DocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, document: Document, version: DocumentVersion, job: ProcessingJob) -> None:
        self.session.add_all((document, version, job))
        await self.session.flush()

    async def get(self, document_id: UUID, organization_id: UUID | None) -> Document | None:
        statement = select(Document).where(Document.id == document_id)
        if organization_id is not None:
            statement = statement.where(Document.organization_id == organization_id)
        return await self.session.scalar(statement)

    async def get_for_update(
        self, document_id: UUID, organization_id: UUID | None
    ) -> Document | None:
        statement = select(Document).where(Document.id == document_id)
        if organization_id is not None:
            statement = statement.where(Document.organization_id == organization_id)
        return await self.session.scalar(statement.with_for_update())

    async def list(self, organization_id: UUID | None) -> builtins.list[Document]:
        statement = select(Document)
        if organization_id is not None:
            statement = statement.where(Document.organization_id == organization_id)
        result = await self.session.scalars(statement.order_by(Document.created_at.desc()))
        return builtins.list(result)

    async def versions(self, document_id: UUID) -> builtins.list[DocumentVersion]:
        result = await self.session.scalars(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document_id)
            .order_by(DocumentVersion.version_number.desc())
        )
        return builtins.list(result)

    async def latest_version(self, document_id: UUID) -> DocumentVersion | None:
        return await self.session.scalar(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document_id)
            .order_by(DocumentVersion.version_number.desc())
            .limit(1)
        )

    async def latest_job(self, document_id: UUID) -> ProcessingJob | None:
        return await self.session.scalar(
            select(ProcessingJob)
            .where(ProcessingJob.resource_id == document_id)
            .order_by(ProcessingJob.created_at.desc())
            .limit(1)
        )

    async def next_version_number(self, document_id: UUID) -> int:
        current = await self.session.scalar(
            select(func.max(DocumentVersion.version_number)).where(
                DocumentVersion.document_id == document_id
            )
        )
        return (current or 0) + 1

    async def delete_jobs(self, document_id: UUID) -> None:
        await self.session.execute(
            delete(ProcessingJob).where(ProcessingJob.resource_id == document_id)
        )
