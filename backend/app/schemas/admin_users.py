"""Public schemas for administrator user-management endpoints."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool


AdminUserRole = Literal["USER", "ADMIN"]


class AdminUserItemResponse(BaseModel):
    """User account fields that are safe for an administrator to view."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(gt=0)
    full_name: str
    username: str
    role: AdminUserRole
    is_active: bool
    created_at: datetime


class AdminUserListResponse(BaseModel):
    """Offset-paginated administrator view of user accounts."""

    items: list[AdminUserItemResponse]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


class AdminUserStatusUpdate(BaseModel):
    """The only account field administrators may change through this API."""

    model_config = ConfigDict(extra="forbid")

    is_active: StrictBool
