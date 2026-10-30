from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.modules.documents.models import (
    ApprovalStatus,
    DocumentStatus,
    JobStatus,
    ProcessingStatus,
)


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    uploaded_by: UUID
    title: str
    original_filename: str
    mime_type: str
    size_bytes: int
    language: str
    status: DocumentStatus
    approval_status: ApprovalStatus
    active_version_id: UUID | None
    created_at: datetime
    updated_at: datetime


class DocumentVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    document_id: UUID
    version_number: int
    original_filename: str
    mime_type: str
    size_bytes: int
    language: str
    checksum: str
    effective_from: datetime | None
    effective_until: datetime | None
    approved_by: UUID | None
    approved_at: datetime | None
    processing_status: ProcessingStatus
    created_at: datetime


class ProcessingJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    job_type: str
    status: JobStatus
    progress: float
    error_message: str | None
    created_at: datetime
    completed_at: datetime | None


class DocumentStatusRead(BaseModel):
    document: DocumentRead
    latest_job: ProcessingJobRead | None
