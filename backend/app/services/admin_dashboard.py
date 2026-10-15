"""Read-only aggregate queries for the administrator dashboard."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import (
    BigInteger,
    Date,
    String,
    cast,
    distinct,
    func,
    literal,
    null,
    or_,
    select,
    union_all,
)
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.chat_session import ChatSession
from app.models.document import Document
from app.models.document_deletion_job import DocumentDeletionJob
from app.models.document_summary import DocumentSummary
from app.models.user import User
from app.services.document_deletion import document_not_being_deleted


logger = logging.getLogger(__name__)

PROCESSING = "PROCESSING"
INDEXING = "INDEXING"
COMPLETED = "COMPLETED"
ACTIVITY_DAYS = 7


class AdminDashboardQueryError(Exception):
    """Raised when an administrator aggregate query cannot complete safely."""


@dataclass(frozen=True, slots=True)
class AdminDashboardOverview:
    user_count: int
    document_count: int
    chat_session_count: int
    processing_document_count: int


@dataclass(frozen=True, slots=True)
class AdminDashboardActivityDay:
    date: date
    registered_user_count: int
    uploaded_document_count: int
    created_chat_session_count: int
    generated_summary_count: int


@dataclass(frozen=True, slots=True)
class AdminDashboardActivity:
    timezone: str
    days: int
    items: list[AdminDashboardActivityDay]


@dataclass(frozen=True, slots=True)
class AdminRecentActivity:
    activity_type: str
    occurred_at: datetime
    resource_id: int
    user_id: int
    document_id: int | None
    session_id: int | None
    file_type: str | None


@dataclass(frozen=True, slots=True)
class AdminRecentActivities:
    items: list[AdminRecentActivity]
    limit: int
    is_audit_log: bool = False


def _rollback_after_query_error(db: Session) -> None:
    try:
        db.rollback()
    except SQLAlchemyError:
        logger.error("Database rollback failed after admin dashboard query error.")


def _utc_now(now: datetime | None) -> datetime:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("now must be timezone-aware.")
    return value.astimezone(timezone.utc)


def _utc_day_expression(db: Session, column):
    bind = db.get_bind()
    if bind.dialect.name == "postgresql":
        return cast(func.timezone("UTC", column), Date)
    return func.date(column)


def _coerce_date(value: date | str) -> date:
    return value if isinstance(value, date) else date.fromisoformat(value)


def _coerce_utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def get_admin_dashboard_overview(db: Session) -> AdminDashboardOverview:
    """Return system-wide counts while excluding active deletion tombstones."""

    live_document = document_not_being_deleted(Document.id)
    user_count = select(func.count(User.id)).scalar_subquery()
    document_count = (
        select(func.count(Document.id))
        .where(live_document)
        .scalar_subquery()
    )
    chat_session_count = (
        select(func.count(ChatSession.id))
        .join(Document, Document.id == ChatSession.document_id)
        .where(live_document)
        .scalar_subquery()
    )
    processing_document_count = (
        select(func.count(distinct(Document.id)))
        .where(
            live_document,
            or_(
                Document.status == PROCESSING,
                Document.rag_status == INDEXING,
            ),
        )
        .scalar_subquery()
    )
    statement = select(
        user_count.label("user_count"),
        document_count.label("document_count"),
        chat_session_count.label("chat_session_count"),
        processing_document_count.label("processing_document_count"),
    )

    try:
        row = db.execute(statement).one()
    except SQLAlchemyError:
        _rollback_after_query_error(db)
        raise AdminDashboardQueryError from None

    return AdminDashboardOverview(
        user_count=int(row.user_count or 0),
        document_count=int(row.document_count or 0),
        chat_session_count=int(row.chat_session_count or 0),
        processing_document_count=int(row.processing_document_count or 0),
    )


def get_admin_dashboard_activity(
    db: Session,
    *,
    now: datetime | None = None,
) -> AdminDashboardActivity:
    """Return seven UTC days using one union of bounded aggregate queries."""

    current_time = _utc_now(now)
    first_day = current_time.date() - timedelta(days=ACTIVITY_DAYS - 1)
    range_start = datetime.combine(first_day, time.min, tzinfo=timezone.utc)
    range_end = datetime.combine(
        current_time.date() + timedelta(days=1),
        time.min,
        tzinfo=timezone.utc,
    )
    live_document = document_not_being_deleted(Document.id)

    def metric_query(metric: str, day_expression, identifier, *filters):
        return (
            select(
                literal(metric).label("metric"),
                day_expression.label("day"),
                func.count(identifier).label("value"),
            )
            .where(*filters)
            .group_by(day_expression)
        )

    registered = metric_query(
        "registered_user_count",
        _utc_day_expression(db, User.created_at),
        User.id,
        User.created_at >= range_start,
        User.created_at < range_end,
    )
    uploaded = metric_query(
        "uploaded_document_count",
        _utc_day_expression(db, Document.created_at),
        Document.id,
        Document.created_at >= range_start,
        Document.created_at < range_end,
        live_document,
    )
    created_sessions = metric_query(
        "created_chat_session_count",
        _utc_day_expression(db, ChatSession.created_at),
        ChatSession.id,
        ChatSession.created_at >= range_start,
        ChatSession.created_at < range_end,
        live_document,
    ).join(Document, Document.id == ChatSession.document_id)
    generated_summaries = metric_query(
        "generated_summary_count",
        _utc_day_expression(db, DocumentSummary.created_at),
        DocumentSummary.id,
        DocumentSummary.created_at >= range_start,
        DocumentSummary.created_at < range_end,
        live_document,
    ).join(Document, Document.id == DocumentSummary.document_id)
    statement = union_all(
        registered,
        uploaded,
        created_sessions,
        generated_summaries,
    )

    try:
        rows = db.execute(statement).all()
    except SQLAlchemyError:
        _rollback_after_query_error(db)
        raise AdminDashboardQueryError from None

    buckets = {
        first_day + timedelta(days=offset): {
            "registered_user_count": 0,
            "uploaded_document_count": 0,
            "created_chat_session_count": 0,
            "generated_summary_count": 0,
        }
        for offset in range(ACTIVITY_DAYS)
    }
    for row in rows:
        day = _coerce_date(row.day)
        if day in buckets:
            buckets[day][row.metric] = int(row.value or 0)

    return AdminDashboardActivity(
        timezone="UTC",
        days=ACTIVITY_DAYS,
        items=[
            AdminDashboardActivityDay(date=day, **metrics)
            for day, metrics in buckets.items()
        ],
    )


def get_admin_recent_activities(
    db: Session,
    *,
    limit: int = 10,
) -> AdminRecentActivities:
    """Return a safe feed derived from current rows, not an audit log."""

    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
        raise ValueError("limit must be an integer from 1 to 50.")

    null_bigint = cast(null(), BigInteger)
    null_file_type = cast(null(), String(10))

    def activity_columns(
        activity_type: str,
        occurred_at,
        resource_id,
        user_id,
        document_id,
        session_id,
        file_type,
    ):
        return select(
            literal(activity_type).label("activity_type"),
            occurred_at.label("occurred_at"),
            resource_id.label("resource_id"),
            user_id.label("user_id"),
            document_id.label("document_id"),
            session_id.label("session_id"),
            file_type.label("file_type"),
        )

    live_document = document_not_being_deleted(Document.id)
    registered = activity_columns(
        "USER_REGISTERED",
        User.created_at,
        User.id,
        User.id,
        null_bigint,
        null_bigint,
        null_file_type,
    )
    uploaded = activity_columns(
        "DOCUMENT_UPLOADED",
        Document.created_at,
        Document.id,
        Document.user_id,
        Document.id,
        null_bigint,
        Document.file_type,
    ).where(live_document)
    processed = activity_columns(
        "DOCUMENT_PROCESSED",
        Document.processed_at,
        Document.id,
        Document.user_id,
        Document.id,
        null_bigint,
        Document.file_type,
    ).where(Document.processed_at.is_not(None), live_document)
    indexed = activity_columns(
        "DOCUMENT_INDEXED",
        Document.indexed_at,
        Document.id,
        Document.user_id,
        Document.id,
        null_bigint,
        Document.file_type,
    ).where(Document.indexed_at.is_not(None), live_document)
    summarized = activity_columns(
        "SUMMARY_CREATED",
        DocumentSummary.created_at,
        DocumentSummary.id,
        Document.user_id,
        Document.id,
        null_bigint,
        Document.file_type,
    ).join(Document, Document.id == DocumentSummary.document_id).where(
        live_document
    )
    session_created = activity_columns(
        "CHAT_SESSION_CREATED",
        ChatSession.created_at,
        ChatSession.id,
        Document.user_id,
        Document.id,
        ChatSession.id,
        Document.file_type,
    ).join(Document, Document.id == ChatSession.document_id).where(live_document)
    deleted = activity_columns(
        "DOCUMENT_DELETED",
        DocumentDeletionJob.completed_at,
        DocumentDeletionJob.id,
        DocumentDeletionJob.user_id,
        DocumentDeletionJob.document_id,
        null_bigint,
        null_file_type,
    ).where(
        DocumentDeletionJob.status == COMPLETED,
        DocumentDeletionJob.completed_at.is_not(None),
    )

    activities = union_all(
        registered,
        uploaded,
        processed,
        indexed,
        summarized,
        session_created,
        deleted,
    ).subquery("admin_recent_activities")
    statement = (
        select(activities)
        .order_by(
            activities.c.occurred_at.desc(),
            activities.c.activity_type.asc(),
            activities.c.resource_id.desc(),
        )
        .limit(limit)
    )

    try:
        rows = db.execute(statement).mappings().all()
    except SQLAlchemyError:
        _rollback_after_query_error(db)
        raise AdminDashboardQueryError from None

    return AdminRecentActivities(
        limit=limit,
        items=[
            AdminRecentActivity(
                activity_type=row["activity_type"],
                occurred_at=_coerce_utc_datetime(row["occurred_at"]),
                resource_id=int(row["resource_id"]),
                user_id=int(row["user_id"]),
                document_id=(
                    int(row["document_id"])
                    if row["document_id"] is not None
                    else None
                ),
                session_id=(
                    int(row["session_id"])
                    if row["session_id"] is not None
                    else None
                ),
                file_type=row["file_type"],
            )
            for row in rows
        ],
    )

