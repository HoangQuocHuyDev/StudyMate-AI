"""Administrator-only dashboard endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import require_roles
from app.models.user import User
from app.schemas.admin_dashboard import (
    AdminDashboardActivityResponse,
    AdminDashboardOverviewResponse,
    AdminRecentActivitiesResponse,
)
from app.services.admin_dashboard import (
    AdminDashboardQueryError,
    get_admin_dashboard_activity,
    get_admin_dashboard_overview,
    get_admin_recent_activities,
)


router = APIRouter(prefix="/admin/dashboard", tags=["Quản trị tổng quan"])
AdminUser = Annotated[User, Depends(require_roles("ADMIN"))]
DatabaseSession = Annotated[Session, Depends(get_db)]


def _query_failed() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Không thể tải số liệu quản trị lúc này.",
    )


@router.get("/overview", response_model=AdminDashboardOverviewResponse)
def get_overview(
    current_admin: AdminUser,
    db: DatabaseSession,
) -> AdminDashboardOverviewResponse:
    """Return system-wide overview counts to an authenticated administrator."""

    del current_admin
    try:
        result = get_admin_dashboard_overview(db)
    except AdminDashboardQueryError:
        raise _query_failed() from None
    return AdminDashboardOverviewResponse.model_validate(
        result,
        from_attributes=True,
    )


@router.get("/activity", response_model=AdminDashboardActivityResponse)
def get_activity(
    current_admin: AdminUser,
    db: DatabaseSession,
) -> AdminDashboardActivityResponse:
    """Return seven days of zero-filled UTC aggregate activity."""

    del current_admin
    try:
        result = get_admin_dashboard_activity(db)
    except AdminDashboardQueryError:
        raise _query_failed() from None
    return AdminDashboardActivityResponse.model_validate(
        result,
        from_attributes=True,
    )


@router.get(
    "/recent-activities",
    response_model=AdminRecentActivitiesResponse,
)
def get_recent_activities(
    current_admin: AdminUser,
    db: DatabaseSession,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> AdminRecentActivitiesResponse:
    """Return recent derived activity without exposing persisted content."""

    del current_admin
    try:
        result = get_admin_recent_activities(db, limit=limit)
    except AdminDashboardQueryError:
        raise _query_failed() from None
    return AdminRecentActivitiesResponse.model_validate(
        result,
        from_attributes=True,
    )

