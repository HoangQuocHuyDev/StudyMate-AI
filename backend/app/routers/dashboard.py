"""Authenticated user dashboard routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.dashboard import DashboardOverviewResponse
from app.services.dashboard import (
    DashboardOverviewQueryError,
    get_dashboard_overview,
)


router = APIRouter(prefix="/dashboard", tags=["Tổng quan"])


@router.get("/overview", response_model=DashboardOverviewResponse)
def get_owned_dashboard_overview(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DashboardOverviewResponse:
    """Return aggregate counts for the authenticated user's live documents."""

    try:
        overview = get_dashboard_overview(db, user_id=current_user.id)
    except DashboardOverviewQueryError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Không thể tải số liệu tổng quan lúc này.",
        ) from None
    return DashboardOverviewResponse.model_validate(
        overview,
        from_attributes=True,
    )
