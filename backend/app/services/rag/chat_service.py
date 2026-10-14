"""RAG chat orchestration with atomic PostgreSQL history persistence."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from time import monotonic
from typing import Callable, Protocol

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.chat_citation import ChatCitation
from app.models.chat_message import ChatMessage
from app.models.chat_session import ChatSession
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.services.document_deletion import document_not_being_deleted
from app.services.summary.concurrency import (
    CapacityConcurrencyCoordinator,
    SummaryConcurrencyError,
    SummaryConcurrencyLimitError,
    SummaryConcurrencyLimits,
    get_capacity_concurrency_coordinator,
)
from app.services.rag.answer_service import (
    AnswerProvider,
    GeminiAnswerRateLimitError,
    GeneratedAnswer,
    LOCAL_GROUNDING_MODEL,
    NO_CONTEXT_ANSWER,
    UNVERIFIED_GROUNDING_ANSWER,
)
from app.services.rag.document_retrieval import (
    MAX_QUERY_LENGTH,
    DocumentRetrievalDeadlineExceededError,
    DocumentRetrievalError,
    RetrievedDocumentChunk,
)


DOCUMENT_READY = "READY"
RAG_READY = "READY"
DEFAULT_CHAT_DEADLINE_SECONDS = 60.0


class RetrievalService(Protocol):
    """Injectable retrieval operation used by one chat turn."""

    def __call__(
        self,
        db: Session,
        *,
        document_id: int,
        user_id: int,
        query: str,
        deadline: "_ChatDeadline | None" = None,
    ) -> list[RetrievedDocumentChunk]:
        """Return verified chunks from the requested document."""


class ChatServiceError(Exception):
    """Base class for errors safe to expose at an API boundary."""


class InvalidChatRequestError(ChatServiceError, ValueError):
    """Raised when identifiers, question, or provider output is invalid."""


class ChatDocumentNotFoundError(ChatServiceError):
    """Raised when a document is absent or not owned by the caller."""


class ChatDocumentNotReadyError(ChatServiceError):
    """Raised when document processing or RAG indexing is incomplete."""


class ChatSessionNotFoundError(ChatServiceError):
    """Raised when a session is absent or belongs to another document."""


class ChatRetrievalError(ChatServiceError):
    """Raised when semantic retrieval cannot be completed safely."""


class ChatAnswerError(ChatServiceError):
    """Raised when the answer provider cannot generate a safe answer."""


class ChatRateLimitError(ChatAnswerError):
    """Raised when Gemini explicitly reports a quota or rate limit."""


class InvalidChatCitationError(ChatServiceError):
    """Raised when answer citations are not a subset of retrieved chunks."""


class ChatPersistenceError(ChatServiceError):
    """Raised when PostgreSQL cannot atomically persist the chat turn."""


class ChatConcurrencyError(ChatPersistenceError):
    """Raised when a concurrent writer conflicts with message ordering."""


class ChatCapacityLimitError(ChatServiceError):
    """Raised when no global or user-scoped Chat execution slot is free."""


class ChatCoordinationError(ChatServiceError):
    """Raised when PostgreSQL Chat coordination is unavailable."""


class ChatDeadlineExceededError(ChatServiceError, TimeoutError):
    """Raised when the complete chat operation exceeds its deadline."""


@dataclass(frozen=True, slots=True)
class _ChatDeadline:
    expires_at: float
    clock: Callable[[], float]

    @classmethod
    def start(
        cls,
        seconds: float,
        clock: Callable[[], float],
    ) -> "_ChatDeadline":
        if (
            isinstance(seconds, bool)
            or not isinstance(seconds, (int, float))
            or not isfinite(float(seconds))
            or seconds <= 0
        ):
            raise InvalidChatRequestError(
                "Chat deadline must be a positive number."
            )
        return cls(expires_at=clock() + float(seconds), clock=clock)

    def remaining_seconds(self) -> float:
        remaining = self.expires_at - self.clock()
        if (
            not isfinite(remaining)
            or remaining <= 0
            or int(remaining * 1_000) < 1
        ):
            raise ChatDeadlineExceededError(
                "The chat operation deadline was exceeded."
            )
        return remaining

    def expired(self) -> bool:
        remaining = self.expires_at - self.clock()
        return (
            not isfinite(remaining)
            or remaining <= 0
            or int(remaining * 1_000) < 1
        )


@dataclass(frozen=True, slots=True)
class ChatCitationResult:
    """Citation metadata returned for an assistant answer."""

    chunk_id: int
    chunk_index: int
    page_number: int | None
    citation_order: int


@dataclass(frozen=True, slots=True)
class ChatTurnResult:
    """Identifiers and safe content created by one completed chat turn."""

    session_id: int
    user_message_id: int
    assistant_message_id: int
    answer_text: str
    model_name: str
    citations: list[ChatCitationResult]


def ask_document(
    db: Session,
    retrieval_service: RetrievalService,
    answer_provider: AnswerProvider,
    *,
    document_id: int,
    user_id: int,
    question: str,
    session_id: int | None = None,
    concurrency_coordinator: CapacityConcurrencyCoordinator | None = None,
    concurrency_limits: SummaryConcurrencyLimits | None = None,
    deadline_seconds: float = DEFAULT_CHAT_DEADLINE_SECONDS,
    clock: Callable[[], float] = monotonic,
) -> ChatTurnResult:
    """Answer one question and atomically append its persisted chat turn."""

    deadline = _ChatDeadline.start(deadline_seconds, clock)
    _validate_identifier(document_id, "document_id")
    _validate_identifier(user_id, "user_id")
    if session_id is not None:
        _validate_identifier(session_id, "session_id")
    normalized_question = _validate_question(question)

    deadline.remaining_seconds()
    _preflight(
        db,
        document_id=document_id,
        user_id=user_id,
        session_id=session_id,
    )
    deadline.remaining_seconds()

    limits = concurrency_limits or SummaryConcurrencyLimits()
    try:
        coordinator = (
            concurrency_coordinator
            or get_capacity_concurrency_coordinator(
                db,
                namespace="chat",
                limits=limits,
            )
        )
        with coordinator.capacity(user_id):
            deadline.remaining_seconds()
            chunks, validated_answer = _generate_answer(
                db,
                retrieval_service,
                answer_provider,
                document_id=document_id,
                user_id=user_id,
                question=normalized_question,
                deadline=deadline,
            )
    except SummaryConcurrencyLimitError:
        _safe_rollback(db)
        raise ChatCapacityLimitError(
            "Chat concurrency capacity is temporarily exhausted."
        ) from None
    except SummaryConcurrencyError:
        _safe_rollback(db)
        raise ChatCoordinationError(
            "Chat concurrency coordination is unavailable."
        ) from None

    deadline.remaining_seconds()
    return _persist_turn(
        db,
        document_id=document_id,
        user_id=user_id,
        session_id=session_id,
        question=normalized_question,
        chunks=chunks,
        answer=validated_answer,
        deadline=deadline,
    )


def _generate_answer(
    db: Session,
    retrieval_service: RetrievalService,
    answer_provider: AnswerProvider,
    *,
    document_id: int,
    user_id: int,
    question: str,
    deadline: _ChatDeadline,
) -> tuple[tuple[RetrievedDocumentChunk, ...], GeneratedAnswer]:
    """Run external retrieval and answer work while capacity is held."""

    try:
        retrieved_chunks = retrieval_service(
            db,
            document_id=document_id,
            user_id=user_id,
            query=question,
            deadline=deadline,
        )
    except DocumentRetrievalDeadlineExceededError:
        _safe_rollback(db)
        raise ChatDeadlineExceededError(
            "The chat operation deadline was exceeded during retrieval."
        ) from None
    except DocumentRetrievalError:
        _safe_rollback(db)
        raise ChatRetrievalError(
            "Relevant document content could not be retrieved."
        ) from None
    except Exception:
        _safe_rollback(db)
        raise ChatRetrievalError(
            "Relevant document content could not be retrieved."
        ) from None

    _end_read_transaction(db)
    deadline.remaining_seconds()
    chunks = _validate_retrieved_chunks(retrieved_chunks, document_id)
    if not chunks:
        return chunks, GeneratedAnswer(
            answer_text=NO_CONTEXT_ANSWER,
            cited_chunk_ids=[],
            model_name=LOCAL_GROUNDING_MODEL,
        )
    try:
        answer = answer_provider.generate_answer(
            question,
            chunks,
            timeout_seconds=deadline.remaining_seconds(),
        )
    except GeminiAnswerRateLimitError:
        if deadline.expired():
            raise ChatDeadlineExceededError(
                "The chat operation deadline was exceeded during answer generation."
            ) from None
        raise ChatRateLimitError(
            "The answer service quota is temporarily unavailable."
        ) from None
    except Exception:
        if deadline.expired():
            raise ChatDeadlineExceededError(
                "The chat operation deadline was exceeded during answer generation."
            ) from None
        raise ChatAnswerError(
            "An answer could not be generated at this time."
        ) from None
    deadline.remaining_seconds()
    return chunks, _validate_answer(answer, chunks)


def _preflight(
    db: Session,
    *,
    document_id: int,
    user_id: int,
    session_id: int | None,
) -> None:
    try:
        document_state = db.execute(
            select(Document.status, Document.rag_status).where(
                Document.id == document_id,
                Document.user_id == user_id,
                document_not_being_deleted(Document.id),
            )
        ).one_or_none()
        session_document_id = None
        if document_state is not None and session_id is not None:
            session_document_id = db.scalar(
                select(ChatSession.document_id).where(ChatSession.id == session_id)
            )
    except SQLAlchemyError:
        _safe_rollback(db)
        raise ChatPersistenceError(
            "Chat state could not be verified."
        ) from None

    _end_read_transaction(db)
    if document_state is None:
        raise ChatDocumentNotFoundError("Document was not found.")
    if (
        document_state.status != DOCUMENT_READY
        or document_state.rag_status != RAG_READY
    ):
        raise ChatDocumentNotReadyError(
            "Document is not ready for RAG chat."
        )
    if session_id is not None and session_document_id != document_id:
        raise ChatSessionNotFoundError(
            "Chat session was not found for this document."
        )


def _persist_turn(
    db: Session,
    *,
    document_id: int,
    user_id: int,
    session_id: int | None,
    question: str,
    chunks: tuple[RetrievedDocumentChunk, ...],
    answer: GeneratedAnswer,
    deadline: _ChatDeadline,
) -> ChatTurnResult:
    chunks_by_id = {chunk.chunk_id: chunk for chunk in chunks}
    now = datetime.now(timezone.utc)
    try:
        deadline.remaining_seconds()
        with db.begin():
            document = db.scalar(
                select(Document)
                .where(
                    Document.id == document_id,
                    Document.user_id == user_id,
                    document_not_being_deleted(Document.id),
                )
                .with_for_update()
            )
            deadline.remaining_seconds()
            if document is None:
                raise ChatDocumentNotFoundError("Document was not found.")
            if (
                document.status != DOCUMENT_READY
                or document.rag_status != RAG_READY
            ):
                raise ChatDocumentNotReadyError(
                    "Document is not ready for RAG chat."
                )

            chat_session = _lock_or_create_session(
                db,
                document_id=document_id,
                session_id=session_id,
                title=question[:255],
                now=now,
            )
            deadline.remaining_seconds()
            next_sequence = db.scalar(
                select(func.coalesce(func.max(ChatMessage.sequence_no), -1) + 1)
                .where(ChatMessage.session_id == chat_session.id)
            )
            deadline.remaining_seconds()
            if not isinstance(next_sequence, int) or next_sequence < 0:
                raise ChatPersistenceError(
                    "Chat message order could not be determined."
                )

            user_message = ChatMessage(
                session_id=chat_session.id,
                sequence_no=next_sequence,
                role="USER",
                content=question,
            )
            assistant_message = ChatMessage(
                session_id=chat_session.id,
                sequence_no=next_sequence + 1,
                role="ASSISTANT",
                content=answer.answer_text,
            )
            db.add_all([user_message, assistant_message])
            db.flush()
            deadline.remaining_seconds()

            persisted_chunks = _load_citation_chunks(
                db,
                document_id=document_id,
                cited_chunk_ids=answer.cited_chunk_ids,
            )
            deadline.remaining_seconds()
            for citation_order, chunk_id in enumerate(answer.cited_chunk_ids):
                if chunk_id not in persisted_chunks:
                    raise InvalidChatCitationError(
                        "An answer citation is no longer valid."
                    )
                db.add(
                    ChatCitation(
                        message_id=assistant_message.id,
                        document_chunk_id=chunk_id,
                        citation_order=citation_order,
                    )
                )

            chat_session.updated_at = now
            db.flush()
            deadline.remaining_seconds()

            result = ChatTurnResult(
                session_id=chat_session.id,
                user_message_id=user_message.id,
                assistant_message_id=assistant_message.id,
                answer_text=answer.answer_text,
                model_name=answer.model_name,
                citations=[
                    ChatCitationResult(
                        chunk_id=chunk_id,
                        chunk_index=chunks_by_id[chunk_id].chunk_index,
                        page_number=chunks_by_id[chunk_id].page_number,
                        citation_order=order,
                    )
                    for order, chunk_id in enumerate(answer.cited_chunk_ids)
                ],
            )
            # This is the final deadline check before SQLAlchemy commits on
            # context exit. A commit that itself finishes after the deadline
            # is still reported as success because its durable outcome is known.
            deadline.remaining_seconds()
    except ChatServiceError:
        _safe_rollback(db)
        raise
    except IntegrityError:
        _safe_rollback(db)
        raise ChatConcurrencyError(
            "A concurrent chat update conflicted with message ordering."
        ) from None
    except SQLAlchemyError:
        _safe_rollback(db)
        raise ChatPersistenceError(
            "The chat turn could not be saved."
        ) from None
    return result


def _lock_or_create_session(
    db: Session,
    *,
    document_id: int,
    session_id: int | None,
    title: str,
    now: datetime,
) -> ChatSession:
    if session_id is not None:
        chat_session = db.scalar(
            _session_for_update_statement(session_id)
        )
        if chat_session is None or chat_session.document_id != document_id:
            raise ChatSessionNotFoundError(
                "Chat session was not found for this document."
            )
        return chat_session

    chat_session = ChatSession(
        document_id=document_id,
        title=title,
        created_at=now,
        updated_at=now,
    )
    db.add(chat_session)
    db.flush()
    return chat_session


def _session_for_update_statement(session_id: int):
    """Build the PostgreSQL row lock used to serialize session writers."""

    return (
        select(ChatSession)
        .where(ChatSession.id == session_id)
        .with_for_update()
    )


def _load_citation_chunks(
    db: Session,
    *,
    document_id: int,
    cited_chunk_ids: list[int],
) -> set[int]:
    if not cited_chunk_ids:
        return set()
    return set(
        db.scalars(
            select(DocumentChunk.id).where(
                DocumentChunk.id.in_(cited_chunk_ids),
                DocumentChunk.document_id == document_id,
            )
        ).all()
    )


def _validate_retrieved_chunks(
    chunks: object,
    document_id: int,
) -> tuple[RetrievedDocumentChunk, ...]:
    if (
        isinstance(chunks, (str, bytes))
        or not isinstance(chunks, Sequence)
    ):
        raise ChatRetrievalError(
            "The retrieval service returned invalid results."
        )
    validated = tuple(chunks)
    seen_ids: set[int] = set()
    for chunk in validated:
        if (
            not isinstance(chunk, RetrievedDocumentChunk)
            or chunk.document_id != document_id
            or chunk.chunk_id <= 0
            or chunk.chunk_index < 0
            or not isinstance(chunk.content, str)
            or not chunk.content
            or (
                chunk.page_number is not None
                and (
                    isinstance(chunk.page_number, bool)
                    or not isinstance(chunk.page_number, int)
                    or chunk.page_number < 1
                )
            )
            or chunk.chunk_id in seen_ids
        ):
            raise ChatRetrievalError(
                "The retrieval service returned invalid results."
            )
        seen_ids.add(chunk.chunk_id)
    return validated


def _validate_answer(
    answer: object,
    chunks: tuple[RetrievedDocumentChunk, ...],
) -> GeneratedAnswer:
    if (
        not isinstance(answer, GeneratedAnswer)
        or not isinstance(answer.answer_text, str)
        or not answer.answer_text.strip()
        or not isinstance(answer.model_name, str)
        or not answer.model_name.strip()
        or not isinstance(answer.cited_chunk_ids, list)
    ):
        raise ChatAnswerError("The answer provider returned an invalid result.")
    normalized_answer = answer.answer_text.strip()
    normalized_model = answer.model_name.strip()
    retrieved_ids = {chunk.chunk_id for chunk in chunks}
    seen_ids: set[int] = set()
    for chunk_id in answer.cited_chunk_ids:
        if (
            isinstance(chunk_id, bool)
            or not isinstance(chunk_id, int)
            or chunk_id <= 0
            or chunk_id not in retrieved_ids
            or chunk_id in seen_ids
        ):
            return GeneratedAnswer(
                answer_text=UNVERIFIED_GROUNDING_ANSWER,
                cited_chunk_ids=[],
                model_name=LOCAL_GROUNDING_MODEL,
            )
        seen_ids.add(chunk_id)
    if not answer.cited_chunk_ids:
        safe_answer = (
            NO_CONTEXT_ANSWER
            if normalized_answer == NO_CONTEXT_ANSWER
            else UNVERIFIED_GROUNDING_ANSWER
        )
        return GeneratedAnswer(
            answer_text=safe_answer,
            cited_chunk_ids=[],
            model_name=(
                normalized_model
                if safe_answer == NO_CONTEXT_ANSWER
                else LOCAL_GROUNDING_MODEL
            ),
        )
    return GeneratedAnswer(
        answer_text=normalized_answer,
        cited_chunk_ids=list(answer.cited_chunk_ids),
        model_name=normalized_model,
    )


def _validate_identifier(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise InvalidChatRequestError(f"{name} must be a positive integer.")


def _validate_question(question: str) -> str:
    if not isinstance(question, str):
        raise InvalidChatRequestError("Question must be a string.")
    normalized = question.strip()
    if not normalized:
        raise InvalidChatRequestError("Question must not be empty.")
    if len(normalized) > MAX_QUERY_LENGTH:
        raise InvalidChatRequestError(
            f"Question must not exceed {MAX_QUERY_LENGTH} characters."
        )
    return normalized


def _end_read_transaction(db: Session) -> None:
    try:
        db.rollback()
    except SQLAlchemyError:
        raise ChatPersistenceError(
            "The database read transaction could not be released."
        ) from None


def _safe_rollback(db: Session) -> None:
    try:
        db.rollback()
    except SQLAlchemyError:
        pass
