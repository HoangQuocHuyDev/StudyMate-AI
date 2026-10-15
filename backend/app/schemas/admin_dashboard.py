"""Public response schemas for the administrator dashboard."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


AdminActivityType = Literal[
    "USER_REGISTERED",
    "DOCUMENT_UPLOADED",
    "DOCUMENT_PROCESSED",
    "DOCUMENT_INDEXED",
    "SUMMARY_CREATED",
    "CHAT_SESSION_CREATED",
    "DOCUMENT_DELETED",
]


class AdminDashboardOverviewResponse(BaseModel):
    """System-wide aggregate counts visible only to administrators."""

    user_count: int = Field(ge=0)
    document_count: int = Field(ge=0)
    chat_session_count: int = Field(ge=0)
    processing_document_count: int = Field(ge=0)


class AdminDashboardActivityDay(BaseModel):
    """One UTC calendar day in the seven-day activity series."""

    date: date
    registered_user_count: int = Field(ge=0)
    uploaded_document_count: int = Field(ge=0)
    created_chat_session_count: int = Field(ge=0)
    generated_summary_count: int = Field(ge=0)


class AdminDashboardActivityResponse(BaseModel):
    """Seven zero-filled UTC activity buckets."""

    timezone: Literal["UTC"] = "UTC"
    days: Literal[7] = 7
    items: list[AdminDashboardActivityDay]


class AdminRecentActivityItem(BaseModel):
    """A safe activity derived from current persisted timestamps."""

    activity_type: AdminActivityType
    occurred_at: datetime
    resource_id: int = Field(gt=0)
    user_id: int = Field(gt=0)
    document_id: int | None = Field(default=None, gt=0)
    session_id: int | None = Field(default=None, gt=0)
    file_type: Literal["PDF", "DOCX"] | None = None


class AdminRecentActivitiesResponse(BaseModel):
    """Recent derived activities; this is not an immutable audit log."""

    items: list[AdminRecentActivityItem]
    limit: int = Field(ge=1, le=50)
    is_audit_log: Literal[False] = False

