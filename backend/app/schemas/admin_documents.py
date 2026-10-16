"""Public schemas for administrator document metadata endpoints."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


AdminDocumentFileType = Literal["PDF", "DOCX"]
AdminDocumentStatus = Literal["UPLOADED", "PROCESSING", "READY", "FAILED"]
AdminDocumentRagStatus = Literal["PENDING", "INDEXING", "READY", "FAILED"]


class AdminDocumentOwnerResponse(BaseModel):
    """Safe owner identity displayed with administrator document metadata."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(gt=0)
    username: str
    full_name: str


class AdminDocumentItemResponse(BaseModel):
    """Document fields safe for an administrator metadata listing."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(gt=0)
    title: str
    original_filename: str
    file_type: AdminDocumentFileType
    file_size: int = Field(gt=0)
    status: AdminDocumentStatus
    rag_status: AdminDocumentRagStatus
    owner: AdminDocumentOwnerResponse
    created_at: datetime
    processed_at: datetime | None
    indexed_at: datetime | None


class AdminDocumentDetailResponse(AdminDocumentItemResponse):
    """Detailed metadata without file contents or private storage fields."""

    mime_type: str
    page_count: int | None
    character_count: int | None
    updated_at: datetime


class AdminDocumentListResponse(BaseModel):
    """Offset-paginated system-wide administrator document list."""

    items: list[AdminDocumentItemResponse]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)
