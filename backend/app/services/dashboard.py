"""Read-only aggregate queries for the authenticated user dashboard."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.chat_session import ChatSession
from app.models.document import Document
from app.models.document_summary import DocumentSummary
from app.services.document_deletion import document_not_being_deleted


logger = logging.getLogger(__name__)

DOCUMENT_READY = "READY"


class DashboardOverviewQueryError(Exception):
    """Raised when dashboard aggregate counts cannot be queried safely."""


@dataclass(frozen=True, slots=True)
class DashboardOverview:
    """Owner-scoped dashboard counts returned by one aggregate statement."""

    document_count: int
    ready_document_count: int
    summary_count: int
    chat_session_count: int


def get_dashboard_overview(db: Session, *, user_id: int) -> DashboardOverview:
    """Return independent counts for live documents owned by one user."""

    if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
        raise ValueError("User identifier must be a positive integer.")

    live_document_filters = (
        Document.user_id == user_id,
        document_not_being_deleted(Document.id),
    )
    document_count = (
        select(func.count(Document.id))
        .where(*live_document_filters)
        .scalar_subquery()
    )
    ready_document_count = (
        select(func.count(Document.id))
        .where(*live_document_filters, Document.status == DOCUMENT_READY)
        .scalar_subquery()
    )
    summary_count = (
        select(func.count(DocumentSummary.id))
        .join(Document, Document.id == DocumentSummary.document_id)
        .where(*live_document_filters)
        .scalar_subquery()
    )
    chat_session_count = (
        select(func.count(ChatSession.id))
        .join(Document, Document.id == ChatSession.document_id)
        .where(*live_document_filters)
        .scalar_subquery()
    )
    statement = select(
        document_count.label("document_count"),
        ready_document_count.label("ready_document_count"),
        summary_count.label("summary_count"),
        chat_session_count.label("chat_session_count"),
    )

    try:
        row = db.execute(statement).one()
    except SQLAlchemyError:
        try:
            db.rollback()
        except SQLAlchemyError:
            logger.error("Database rollback failed after dashboard query error.")
        raise DashboardOverviewQueryError(
            "Could not query dashboard overview."
        ) from None

    return DashboardOverview(
        document_count=int(row.document_count or 0),
        ready_document_count=int(row.ready_document_count or 0),
        summary_count=int(row.summary_count or 0),
        chat_session_count=int(row.chat_session_count or 0),
    )
