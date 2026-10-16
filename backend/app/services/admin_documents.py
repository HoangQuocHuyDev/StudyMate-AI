"""Read-only administrator queries for system-wide document metadata."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.user import User
from app.services.document_deletion import document_not_being_deleted


class AdminDocumentQueryError(Exception):
    """Raised when administrator document metadata cannot be queried safely."""


class AdminDocumentNotFoundError(Exception):
    """Raised when a visible document does not exist."""


@dataclass(frozen=True, slots=True)
class AdminDocumentOwner:
    id: int
    username: str
    full_name: str


@dataclass(frozen=True, slots=True)
class AdminDocumentItem:
    id: int
    title: str
    original_filename: str
    file_type: str
    file_size: int
    status: str
    rag_status: str
    owner: AdminDocumentOwner
    created_at: datetime
    processed_at: datetime | None
    indexed_at: datetime | None


@dataclass(frozen=True, slots=True)
class AdminDocumentDetail(AdminDocumentItem):
    mime_type: str
    page_count: int | None
    character_count: int | None
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class AdminDocumentListPage:
    items: list[AdminDocumentItem]
    total: int


def _escape_like_literal(value: str) -> str:
    """Escape LIKE wildcards and the escape character itself."""

    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _owner(user: User) -> AdminDocumentOwner:
    return AdminDocumentOwner(
        id=user.id,
        username=user.username,
        full_name=user.full_name,
    )


def _item(document: Document, user: User) -> AdminDocumentItem:
    return AdminDocumentItem(
        id=document.id,
        title=document.title,
        original_filename=document.original_filename,
        file_type=document.file_type,
        file_size=document.file_size,
        status=document.status,
        rag_status=document.rag_status,
        owner=_owner(user),
        created_at=document.created_at,
        processed_at=document.processed_at,
        indexed_at=document.indexed_at,
    )


def list_admin_documents(
    db: Session,
    *,
    limit: int,
    offset: int,
    search: str = "",
    file_type: str | None = None,
    status: str | None = None,
    rag_status: str | None = None,
) -> AdminDocumentListPage:
    """Return one stable system-wide page of non-tombstoned documents."""

    filters = [document_not_being_deleted(Document.id)]
    normalized_search = search.strip()
    if normalized_search:
        escaped_search = _escape_like_literal(normalized_search)
        pattern = f"%{escaped_search}%"
        filters.append(
            or_(
                Document.title.ilike(pattern, escape="\\"),
                Document.original_filename.ilike(pattern, escape="\\"),
            )
        )
    if file_type is not None:
        filters.append(Document.file_type == file_type)
    if status is not None:
        filters.append(Document.status == status)
    if rag_status is not None:
        filters.append(Document.rag_status == rag_status)

    count_statement = select(func.count(Document.id)).where(*filters)
    page_statement = (
        select(Document, User)
        .join(User, User.id == Document.user_id)
        .where(*filters)
        .order_by(Document.created_at.desc(), Document.id.desc())
        .offset(offset)
        .limit(limit)
    )

    try:
        total = int(db.scalar(count_statement) or 0)
        rows = db.execute(page_statement).all()
    except SQLAlchemyError:
        db.rollback()
        raise AdminDocumentQueryError from None

    return AdminDocumentListPage(
        items=[_item(document, user) for document, user in rows],
        total=total,
    )


def get_admin_document(db: Session, *, document_id: int) -> AdminDocumentDetail:
    """Return safe metadata for one non-tombstoned document and its owner."""

    statement = (
        select(Document, User)
        .join(User, User.id == Document.user_id)
        .where(
            Document.id == document_id,
            document_not_being_deleted(Document.id),
        )
    )
    try:
        row = db.execute(statement).one_or_none()
    except SQLAlchemyError:
        db.rollback()
        raise AdminDocumentQueryError from None

    if row is None:
        raise AdminDocumentNotFoundError

    document, user = row
    base = _item(document, user)
    return AdminDocumentDetail(
        **{
            field: getattr(base, field)
            for field in AdminDocumentItem.__dataclass_fields__
        },
        mime_type=document.mime_type,
        page_count=document.page_count,
        character_count=document.character_count,
        updated_at=document.updated_at,
    )
