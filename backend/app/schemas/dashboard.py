"""Public response schemas for the authenticated user dashboard."""

from pydantic import BaseModel, Field


class DashboardOverviewResponse(BaseModel):
    """Owner-scoped aggregate counts displayed on the user dashboard."""

    document_count: int = Field(ge=0)
    ready_document_count: int = Field(ge=0)
    summary_count: int = Field(ge=0)
    chat_session_count: int = Field(ge=0)
