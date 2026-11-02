from collections.abc import Iterator
from pathlib import Path
from typing import cast
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from minio import Minio
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.dependencies import (
    get_app_settings,
    get_current_user,
    get_db_session,
    require_roles,
)
from app.modules.documents.models import Document, DocumentVersion
from app.modules.documents.repository import DocumentRepository
from app.modules.documents.schemas import (
    DocumentRead,
    DocumentStatusRead,
    DocumentVersionRead,
)
from app.modules.documents.service import DocumentService
from app.modules.users.models import User, UserRole

router = APIRouter(prefix="/documents", tags=["documents"])


def service(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_app_settings),
) -> DocumentService:
    return DocumentService(
        DocumentRepository(session), cast(Minio, request.app.state.minio), settings
    )


admin = require_roles(UserRole.SUPER_ADMIN, UserRole.ORG_ADMIN)


@router.post("/upload", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    title: str = Form(..., min_length=2, max_length=500),
    language: str = Form(..., pattern="^(kk|ru|en)$"),
    organization_id: UUID | None = Form(None),
    actor: User = Depends(admin),
    document_service: DocumentService = Depends(service),
) -> Document:
    return await document_service.upload(actor, file, title, language, organization_id)


@router.get("", response_model=list[DocumentRead])
async def list_documents(
    organization_id: UUID | None = None,
    actor: User = Depends(admin),
    document_service: DocumentService = Depends(service),
) -> list[Document]:
    return await document_service.list(actor, organization_id)


@router.get("/{document_id}", response_model=DocumentRead)
async def get_document(
    document_id: UUID,
    actor: User = Depends(admin),
    document_service: DocumentService = Depends(service),
) -> Document:
    return await document_service.get(actor, document_id)


@router.get("/{document_id}/versions", response_model=list[DocumentVersionRead])
async def get_versions(
    document_id: UUID,
    actor: User = Depends(admin),
    document_service: DocumentService = Depends(service),
) -> list[DocumentVersion]:
    document = await document_service.get(actor, document_id)
    return await document_service.repository.versions(document.id)


@router.post(
    "/{document_id}/versions",
    response_model=DocumentVersionRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document_version(
    document_id: UUID,
    file: UploadFile = File(...),
    language: str | None = Form(None, pattern="^(kk|ru|en)$"),
    actor: User = Depends(admin),
    document_service: DocumentService = Depends(service),
) -> DocumentVersion:
    return await document_service.upload_version(actor, document_id, file, language)


@router.get("/{document_id}/status", response_model=DocumentStatusRead)
async def get_status(
    document_id: UUID,
    actor: User = Depends(admin),
    document_service: DocumentService = Depends(service),
) -> DocumentStatusRead:
    return await document_service.status(actor, document_id)


@router.get("/{document_id}/download", response_class=StreamingResponse)
async def download_document(
    document_id: UUID,
    actor: User = Depends(get_current_user),
    document_service: DocumentService = Depends(service),
) -> StreamingResponse:
    document, response = await document_service.download(actor, document_id)

    def body() -> Iterator[bytes]:
        try:
            yield from response.stream(amt=64 * 1024)
        finally:
            response.close()
            response.release_conn()

    return StreamingResponse(
        body(),
        media_type=document.mime_type,
        headers={
            "Content-Disposition": (
                f'inline; filename="document{Path(document.original_filename).suffix.lower()}"; '
                f"filename*=UTF-8''{quote(document.original_filename)}"
            )
        },
    )


@router.post("/{document_id}/approve", response_model=DocumentRead)
async def approve_document(
    document_id: UUID,
    actor: User = Depends(admin),
    document_service: DocumentService = Depends(service),
) -> Document:
    return await document_service.approve(actor, document_id)


@router.post("/{document_id}/archive", response_model=DocumentRead)
async def archive_document(
    document_id: UUID,
    actor: User = Depends(admin),
    document_service: DocumentService = Depends(service),
) -> Document:
    return await document_service.archive(actor, document_id)


@router.post("/{document_id}/reindex", response_model=DocumentStatusRead)
async def reindex_document(
    document_id: UUID,
    actor: User = Depends(admin),
    document_service: DocumentService = Depends(service),
) -> DocumentStatusRead:
    return await document_service.reindex(actor, document_id)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: UUID,
    actor: User = Depends(admin),
    document_service: DocumentService = Depends(service),
) -> None:
    await document_service.delete(actor, document_id)
