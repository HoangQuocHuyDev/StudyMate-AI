"""Public request and response schemas for document summaries."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class DocumentSummaryType(str, Enum):
    SHORT = "SHORT"
    STANDARD = "STANDARD"
    DETAILED = "DETAILED"


class DocumentSummaryGenerateRequest(BaseModel):
    document_id: int = Field(gt=0)
    summary_type: DocumentSummaryType


class DocumentSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    summary_id: int
    document_id: int
    summary_type: str
    content: str
    model_name: str
    created_at: datetime
    updated_at: datetime


class DocumentSummaryGenerateResponse(DocumentSummaryResponse):
    from_cache: bool


class DocumentSummaryListResponse(BaseModel):
    document_id: int
    items: list[DocumentSummaryResponse]
