"""Owner-scoped, read-only PostgreSQL access for RAG chat history."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

from sqlalchemy import func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, joinedload

from app.models.chat_citation import ChatCitation
from app.models.chat_message import ChatMessage
from app.models.chat_session import ChatSession
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.services.document_deletion import document_not_being_deleted


class ChatHistoryError(Exception):
    """Base error for safe chat history reads."""


class ChatHistoryNotFoundError(ChatHistoryError):
    """Raised when an owner-scoped document or session is absent."""


class ChatHistoryInfrastructureError(ChatHistoryError):
    """Raised when PostgreSQL chat history cannot be read safely."""


@dataclass(frozen=True, slots=True)
class ChatSessionHistoryItem:
    id: int
    document_id: int
    title: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ChatHistoryCitation:
    chunk_id: int
    chunk_index: int
    page_number: int | None
    citation_order: int


@dataclass(frozen=True, slots=True)
class ChatMessageHistoryItem:
    id: int
    session_id: int
    sequence_no: int
    role: str
    content: str
    created_at: datetime
    citations: list[ChatHistoryCitation]


@dataclass(frozen=True, slots=True)
class ChatSessionHistoryPage:
    items: list[ChatSessionHistoryItem]
    total: int


ChatHistoryPeriod = Literal["today", "week", "month"]


@dataclass(frozen=True, slots=True)
class ChatHistoryListItem:
    session_id: int
    document_id: int
    title: str
    document_title: str
    file_type: str
    created_at: datetime
    updated_at: datetime
    last_message_preview: str | None


@dataclass(frozen=True, slots=True)
class ChatHistoryListPage:
    items: list[ChatHistoryListItem]
    total: int


@dataclass(frozen=True, slots=True)
class ChatMessageHistoryPage:
    session_id: int
    items: list[ChatMessageHistoryItem]
    total: int


@dataclass(frozen=True, slots=True)
class ChatMessageCursorPage:
    session_id: int
    items: list[ChatMessageHistoryItem]
    total: int
    next_before_sequence_no: int | None
    has_more: bool


@dataclass(frozen=True, slots=True)
class ChatCitationDetail:
    chunk_id: int
    document_id: int
    chunk_index: int
    content: str
    page_number: int | None
    citation_order: int


def list_owned_chat_history(
    db: Session,
    *,
    user_id: int,
    limit: int,
    offset: int,
    search: str = "",
    period: ChatHistoryPeriod | None = None,
    now: datetime | None = None,
) -> ChatHistoryListPage:
    """List one user's sessions across active documents without N+1 reads."""

    normalized_search = search.strip()
    filters = [
        Document.user_id == user_id,
        document_not_being_deleted(Document.id),
    ]
    if normalized_search:
        escaped_search = _escape_like(normalized_search)
        pattern = f"%{escaped_search}%"
        filters.append(
            or_(
                ChatSession.title.ilike(pattern, escape="\\"),
                Document.title.ilike(pattern, escape="\\"),
            )
        )
    period_start = _period_start(period, now=now)
    if period_start is not None:
        filters.append(ChatSession.updated_at >= period_start)

    last_message_content = (
        select(ChatMessage.content)
        .where(ChatMessage.session_id == ChatSession.id)
        .order_by(ChatMessage.sequence_no.desc(), ChatMessage.id.desc())
        .limit(1)
        .correlate(ChatSession)
        .scalar_subquery()
    )

    try:
        total = db.scalar(
            select(func.count(ChatSession.id))
            .select_from(ChatSession)
            .join(Document, Document.id == ChatSession.document_id)
            .where(*filters)
        ) or 0
        rows = db.execute(
            select(
                ChatSession.id,
                ChatSession.document_id,
                ChatSession.title,
                Document.title.label("document_title"),
                Document.file_type,
                ChatSession.created_at,
                ChatSession.updated_at,
                func.substr(last_message_content, 1, 200).label(
                    "last_message_preview"
                ),
            )
            .select_from(ChatSession)
            .join(Document, Document.id == ChatSession.document_id)
            .where(*filters)
            .order_by(ChatSession.updated_at.desc(), ChatSession.id.desc())
            .offset(offset)
            .limit(limit)
        ).all()
    except SQLAlchemyError:
        _safe_rollback(db)
        raise ChatHistoryInfrastructureError(
            "Combined chat history could not be loaded."
        ) from None

    return ChatHistoryListPage(
        items=[
            ChatHistoryListItem(
                session_id=row.id,
                document_id=row.document_id,
                title=row.title,
                document_title=row.document_title,
                file_type=row.file_type,
                created_at=row.created_at,
                updated_at=row.updated_at,
                last_message_preview=row.last_message_preview,
            )
            for row in rows
        ],
        total=int(total),
    )


def list_chat_sessions(
    db: Session,
    *,
    document_id: int,
    user_id: int,
    limit: int,
    offset: int,
) -> ChatSessionHistoryPage:
    """List sessions for one owned document in stable recent-first order."""

    try:
        owned = db.scalar(
            select(Document.id).where(
                Document.id == document_id,
                Document.user_id == user_id,
                document_not_being_deleted(Document.id),
            )
        )
        if owned is None:
            raise ChatHistoryNotFoundError("Document was not found.")
        total = db.scalar(
            select(func.count(ChatSession.id)).where(
                ChatSession.document_id == document_id
            )
        ) or 0
        sessions = db.scalars(
            select(ChatSession)
            .where(ChatSession.document_id == document_id)
            .order_by(ChatSession.updated_at.desc(), ChatSession.id.desc())
            .offset(offset)
            .limit(limit)
        ).all()
    except ChatHistoryNotFoundError:
        raise
    except SQLAlchemyError:
        _safe_rollback(db)
        raise ChatHistoryInfrastructureError(
            "Chat sessions could not be loaded."
        ) from None
    return ChatSessionHistoryPage(
        items=[
            ChatSessionHistoryItem(
                id=item.id,
                document_id=item.document_id,
                title=item.title,
                created_at=item.created_at,
                updated_at=item.updated_at,
            )
            for item in sessions
        ],
        total=int(total),
    )


def list_chat_messages(
    db: Session,
    *,
    session_id: int,
    user_id: int,
    limit: int,
    offset: int,
) -> ChatMessageHistoryPage:
    """Load one owned session page with citations in a bounded query count."""

    try:
        document_id = _owned_session_document_id(
            db,
            session_id=session_id,
            user_id=user_id,
        )
        total = db.scalar(
            select(func.count(ChatMessage.id)).where(
                ChatMessage.session_id == session_id
            )
        ) or 0
        messages = db.execute(
            select(ChatMessage)
            .options(
                joinedload(ChatMessage.citations).joinedload(
                    ChatCitation.document_chunk
                )
            )
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.sequence_no.asc(), ChatMessage.id.asc())
            .offset(offset)
            .limit(limit)
        ).unique().scalars().all()
    except ChatHistoryNotFoundError:
        raise
    except SQLAlchemyError:
        _safe_rollback(db)
        raise ChatHistoryInfrastructureError(
            "Chat messages could not be loaded."
        ) from None

    return ChatMessageHistoryPage(
        session_id=session_id,
        items=_history_items(messages, document_id),
        total=int(total),
    )


def list_chat_messages_cursor(
    db: Session,
    *,
    session_id: int,
    user_id: int,
    limit: int,
    before_sequence_no: int | None = None,
) -> ChatMessageCursorPage:
    """Load the newest owned messages before an immutable sequence cursor."""

    if not 1 <= limit <= 50:
        raise ValueError("Cursor page limit must be between 1 and 50.")
    if before_sequence_no is not None and before_sequence_no < 0:
        raise ValueError("Message cursor must be nonnegative.")

    try:
        document_id = _owned_session_document_id(
            db,
            session_id=session_id,
            user_id=user_id,
        )
        total = db.scalar(
            select(func.count(ChatMessage.id)).where(
                ChatMessage.session_id == session_id
            )
        ) or 0
        statement = (
            select(ChatMessage)
            .options(
                joinedload(ChatMessage.citations).joinedload(
                    ChatCitation.document_chunk
                )
            )
            .where(ChatMessage.session_id == session_id)
        )
        if before_sequence_no is not None:
            statement = statement.where(
                ChatMessage.sequence_no < before_sequence_no
            )
        recent_first = (
            db.execute(
                statement.order_by(
                    ChatMessage.sequence_no.desc(),
                    ChatMessage.id.desc(),
                ).limit(limit + 1)
            )
            .unique()
            .scalars()
            .all()
        )
    except ChatHistoryNotFoundError:
        raise
    except SQLAlchemyError:
        _safe_rollback(db)
        raise ChatHistoryInfrastructureError(
            "Chat messages could not be loaded."
        ) from None

    has_more = len(recent_first) > limit
    page_messages = list(reversed(recent_first[:limit]))
    next_cursor = (
        page_messages[0].sequence_no if has_more and page_messages else None
    )
    return ChatMessageCursorPage(
        session_id=session_id,
        items=_history_items(page_messages, document_id),
        total=int(total),
        next_before_sequence_no=next_cursor,
        has_more=has_more,
    )


def _owned_session_document_id(
    db: Session,
    *,
    session_id: int,
    user_id: int,
) -> int:
    document_id = db.scalar(
        select(ChatSession.document_id)
        .join(Document, Document.id == ChatSession.document_id)
        .where(
            ChatSession.id == session_id,
            Document.user_id == user_id,
            document_not_being_deleted(Document.id),
        )
    )
    if document_id is None:
        raise ChatHistoryNotFoundError("Chat session was not found.")
    return document_id


def _history_items(
    messages: list[ChatMessage],
    document_id: int,
) -> list[ChatMessageHistoryItem]:
    return [
        ChatMessageHistoryItem(
            id=message.id,
            session_id=message.session_id,
            sequence_no=message.sequence_no,
            role=message.role,
            content=message.content,
            created_at=message.created_at,
            citations=_verified_citations(message, document_id),
        )
        for message in messages
    ]


def _verified_citations(
    message: ChatMessage,
    document_id: int,
) -> list[ChatHistoryCitation]:
    if message.role != "ASSISTANT":
        return []
    return [
        ChatHistoryCitation(
            chunk_id=citation.document_chunk_id,
            chunk_index=citation.document_chunk.chunk_index,
            page_number=citation.document_chunk.page_number,
            citation_order=citation.citation_order,
        )
        for citation in sorted(
            message.citations,
            key=lambda item: item.citation_order,
        )
        if citation.document_chunk is not None
        and citation.document_chunk.document_id == document_id
    ]


def get_chat_citation_detail(
    db: Session,
    *,
    chunk_id: int,
    session_id: int,
    message_id: int,
    user_id: int,
) -> ChatCitationDetail:
    """Return one citation only when its complete ownership chain is valid."""

    try:
        row = db.execute(
            select(DocumentChunk, ChatCitation.citation_order)
            .select_from(ChatCitation)
            .join(ChatMessage, ChatMessage.id == ChatCitation.message_id)
            .join(ChatSession, ChatSession.id == ChatMessage.session_id)
            .join(Document, Document.id == ChatSession.document_id)
            .join(
                DocumentChunk,
                DocumentChunk.id == ChatCitation.document_chunk_id,
            )
            .where(
                Document.user_id == user_id,
                document_not_being_deleted(Document.id),
                ChatSession.id == session_id,
                ChatMessage.id == message_id,
                ChatMessage.session_id == session_id,
                ChatMessage.role == "ASSISTANT",
                ChatCitation.message_id == message_id,
                ChatCitation.document_chunk_id == chunk_id,
                DocumentChunk.id == chunk_id,
                DocumentChunk.document_id == ChatSession.document_id,
            )
        ).one_or_none()
        if row is None:
            raise ChatHistoryNotFoundError("Chat citation was not found.")
    except ChatHistoryNotFoundError:
        raise
    except SQLAlchemyError:
        _safe_rollback(db)
        raise ChatHistoryInfrastructureError(
            "Chat citation could not be loaded."
        ) from None

    chunk, citation_order = row
    return ChatCitationDetail(
        chunk_id=chunk.id,
        document_id=chunk.document_id,
        chunk_index=chunk.chunk_index,
        content=chunk.content,
        page_number=chunk.page_number,
        citation_order=citation_order,
    )


def _escape_like(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


def _period_start(
    period: ChatHistoryPeriod | None,
    *,
    now: datetime | None,
) -> datetime | None:
    if period is None:
        return None
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("History clock must be timezone-aware.")
    current = current.astimezone(timezone.utc)
    if period == "today":
        return current.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "week":
        return current - timedelta(days=7)
    if period == "month":
        return current - timedelta(days=30)
    raise ValueError("History period must be today, week, month, or omitted.")


def _safe_rollback(db: Session) -> None:
    try:
        db.rollback()
    except SQLAlchemyError:
        pass
