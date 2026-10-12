"""Public schemas for document metadata."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


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
