"""Public schemas for document metadata."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict


class DocumentFileType(str, Enum):
    """Supported public document type filter values."""

    PDF = "PDF"
    DOCX = "DOCX"

    @classmethod
    def _missing_(cls, value: object) -> "DocumentFileType | None":
        if isinstance(value, str):
            normalized = value.upper()
            for member in cls:
                if member.value == normalized:
                    return member
        return None


class DocumentResponse(BaseModel):
    """Document metadata safe to return to an authenticated client."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    original_filename: str
    file_type: str
    mime_type: str
    file_size: int
    status: str
    created_at: datetime


class DocumentListResponse(BaseModel):
    """Paginated document metadata for one authenticated owner."""

    items: list[DocumentResponse]
    page: int
    page_size: int
    total: int
    total_pages: int


class DocumentDetailResponse(DocumentResponse):
    """Detailed document metadata without private storage information."""

    updated_at: datetime
    character_count: int | None
    page_count: int | None
    processed_at: datetime | None
    rag_status: str
    indexed_at: datetime | None


class DocumentPreviewResponse(BaseModel):
    """Owner-scoped plain-text preview extracted from one DOCX source file."""

    model_config = ConfigDict(from_attributes=True)

    document_id: int
    title: str
    original_filename: str
    file_type: str
    content: str
    character_count: int


class DocumentProcessingStatusResponse(BaseModel):
    """Safe processing and indexing state for one owned document."""

    model_config = ConfigDict(from_attributes=True)

    document_id: int
    status: str
    rag_status: str
    character_count: int | None
    page_count: int | None
    processed_at: datetime | None
    indexed_at: datetime | None
    chunk_count: int


class DocumentIndexingResponse(BaseModel):
    """Safe result of synchronously indexing one owned document."""

    model_config = ConfigDict(from_attributes=True)

    document_id: int
    rag_status: str
    vector_count: int
    indexed_at: datetime


class DocumentRagStatusResponse(BaseModel):
    """Safe PostgreSQL-backed RAG status for one owned document."""

    model_config = ConfigDict(from_attributes=True)

    document_id: int
    status: str
    rag_status: str
    chunk_count: int
    indexed_at: datetime | None
    can_index: bool
