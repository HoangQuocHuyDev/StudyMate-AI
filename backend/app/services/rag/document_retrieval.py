"""Owner-scoped semantic retrieval with PostgreSQL result verification."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import isfinite
from numbers import Real
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.services.document_deletion import document_not_being_deleted
from app.services.rag.chroma_vector_store import ChunkQueryResult
from app.services.rag.embedding_service import EmbeddingProvider


DOCUMENT_READY = "READY"
RAG_READY = "READY"
DEFAULT_TOP_K = 5
MAX_TOP_K = 20
MAX_QUERY_LENGTH = 2_000
_VECTOR_ID_PATTERN = re.compile(r"^document_chunk:([1-9][0-9]*)$")
logger = logging.getLogger(__name__)


class DocumentRetrievalVectorStore(Protocol):
    """Read-only vector operation needed by semantic retrieval."""

    def query_chunks(
        self,
        query_embedding: Sequence[float],
        *,
        user_id: int,
        document_id: int,
        limit: int,
    ) -> list[ChunkQueryResult]:
        """Return owner- and document-filtered matches in relevance order."""


class RetrievalDeadline(Protocol):
    """Monotonic operation deadline supplied by a higher-level service."""

    def remaining_seconds(self) -> float:
        """Return positive remaining time or raise when expired."""


class DocumentRetrievalError(Exception):
    """Base error for safe document retrieval failures."""


class InvalidDocumentRetrievalRequestError(DocumentRetrievalError, ValueError):
    """Raised when identifiers, query, or result limit are invalid."""


class DocumentRetrievalNotFoundError(DocumentRetrievalError):
    """Raised when a document is absent or not owned by the caller."""


class DocumentNotRetrievableError(DocumentRetrievalError):
    """Raised when processing or indexing state does not allow retrieval."""


class DocumentRetrievalProviderError(DocumentRetrievalError):
    """Raised when embedding or vector search cannot be completed."""


class DocumentQueryEmbeddingError(DocumentRetrievalProviderError):
    """Raised when Gemini cannot embed the sanitized query."""


class DocumentVectorSearchError(DocumentRetrievalProviderError):
    """Raised when ChromaDB cannot complete the filtered search."""


class DocumentRetrievalConsistencyError(DocumentRetrievalError):
    """Raised when Chroma results cannot be reconciled with PostgreSQL."""


class DocumentRetrievalInfrastructureError(DocumentRetrievalError):
    """Raised when PostgreSQL state cannot be read safely."""


class DocumentRetrievalDeadlineExceededError(
    DocumentRetrievalError,
    TimeoutError,
):
    """Raised when the enclosing RAG operation deadline is exhausted."""


@dataclass(frozen=True, slots=True)
class RetrievedDocumentChunk:
    """Verified retrieval result suitable for a future RAG citation."""

    chunk_id: int
    document_id: int
    chunk_index: int
    content: str
    page_number: int | None
    distance: float


def retrieve_document_chunks(
    db: Session,
    embedder: EmbeddingProvider,
    vector_store: DocumentRetrievalVectorStore,
    *,
    document_id: int,
    user_id: int,
    query: str,
    top_k: int = DEFAULT_TOP_K,
    max_cosine_distance: float | None = None,
    deadline: RetrievalDeadline | None = None,
) -> list[RetrievedDocumentChunk]:
    """Retrieve and verify relevant chunks for one ready, owned document."""

    _validate_identifier(document_id, "document_id")
    _validate_identifier(user_id, "user_id")
    normalized_query = _validate_query(query)
    _validate_top_k(top_k)
    _validate_max_cosine_distance(max_cosine_distance)
    _remaining_seconds(deadline)
    _assert_document_retrievable(
        db,
        document_id=document_id,
        user_id=user_id,
    )
    _end_read_transaction(db)
    remaining_seconds = _remaining_seconds(deadline)

    try:
        query_embedding = embedder.embed_query(
            normalized_query,
            timeout_seconds=remaining_seconds,
        )
    except Exception:
        if _deadline_expired(deadline):
            raise DocumentRetrievalDeadlineExceededError(
                "The retrieval deadline was exceeded during embedding."
            ) from None
        raise DocumentQueryEmbeddingError(
            "The query embedding could not be generated."
        ) from None
    _remaining_seconds(deadline)

    try:
        _remaining_seconds(deadline)
        vector_results = vector_store.query_chunks(
            query_embedding,
            user_id=user_id,
            document_id=document_id,
            limit=top_k,
        )
    except Exception:
        if _deadline_expired(deadline):
            raise DocumentRetrievalDeadlineExceededError(
                "The retrieval deadline was exceeded during vector search."
            ) from None
        raise DocumentVectorSearchError(
            "Document vectors could not be queried."
        ) from None
    _remaining_seconds(deadline)

    if not isinstance(vector_results, list):
        raise DocumentRetrievalConsistencyError(
            "The vector index returned an invalid result set."
        )
    if not vector_results:
        return []
    verified_results = _verify_vector_results(
        db,
        vector_results=vector_results,
        document_id=document_id,
        user_id=user_id,
    )
    _remaining_seconds(deadline)
    if max_cosine_distance is None:
        return verified_results
    return [
        chunk
        for chunk in verified_results
        if chunk.distance <= max_cosine_distance
    ]


def _remaining_seconds(deadline: RetrievalDeadline | None) -> float | None:
    if deadline is None:
        return None
    try:
        remaining = deadline.remaining_seconds()
    except TimeoutError:
        raise DocumentRetrievalDeadlineExceededError(
            "The retrieval deadline was exceeded."
        ) from None
    if (
        isinstance(remaining, bool)
        or not isinstance(remaining, Real)
        or not isfinite(float(remaining))
        or float(remaining) <= 0
    ):
        raise DocumentRetrievalDeadlineExceededError(
            "The retrieval deadline was exceeded."
        )
    return float(remaining)


def _deadline_expired(deadline: RetrievalDeadline | None) -> bool:
    if deadline is None:
        return False
    try:
        _remaining_seconds(deadline)
    except DocumentRetrievalDeadlineExceededError:
        return True
    return False


def _assert_document_retrievable(
    db: Session,
    *,
    document_id: int,
    user_id: int,
) -> None:
    chunk_count = (
        select(func.count(DocumentChunk.id))
        .where(DocumentChunk.document_id == Document.id)
        .correlate(Document)
        .scalar_subquery()
    )
    statement = select(
        Document.status,
        Document.rag_status,
        chunk_count.label("chunk_count"),
    ).where(
        Document.id == document_id,
        Document.user_id == user_id,
        document_not_being_deleted(Document.id),
    )
    try:
        row = db.execute(statement).one_or_none()
    except SQLAlchemyError:
        _safe_rollback(db)
        raise DocumentRetrievalInfrastructureError(
            "Document state could not be verified."
        ) from None
    if row is None:
        raise DocumentRetrievalNotFoundError("Document was not found.")
    if (
        row.status != DOCUMENT_READY
        or row.rag_status != RAG_READY
        or int(row.chunk_count) < 1
    ):
        raise DocumentNotRetrievableError(
            "Document is not ready for semantic retrieval."
        )


def _verify_vector_results(
    db: Session,
    *,
    vector_results: list[ChunkQueryResult],
    document_id: int,
    user_id: int,
) -> list[RetrievedDocumentChunk]:
    candidates: list[tuple[int, ChunkQueryResult]] = []
    seen_chunk_ids: set[int] = set()
    discarded_count = 0
    for result in vector_results:
        parsed = _parse_vector_result(
            result,
            document_id=document_id,
            user_id=user_id,
        )
        if parsed is None:
            discarded_count += 1
            continue
        chunk_id = parsed
        if chunk_id in seen_chunk_ids:
            discarded_count += 1
            continue
        seen_chunk_ids.add(chunk_id)
        candidates.append((chunk_id, result))

    chunks_by_id = _load_owned_chunks(
        db,
        chunk_ids=[chunk_id for chunk_id, _ in candidates],
        document_id=document_id,
        user_id=user_id,
    )
    verified: list[RetrievedDocumentChunk] = []
    stale_content_count = 0
    for chunk_id, result in candidates:
        chunk = chunks_by_id.get(chunk_id)
        if chunk is None or not _metadata_matches_chunk(result.metadata, chunk):
            discarded_count += 1
            continue
        if result.content != chunk.content:
            stale_content_count += 1
        verified.append(
            RetrievedDocumentChunk(
                chunk_id=chunk.id,
                document_id=chunk.document_id,
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                page_number=chunk.page_number,
                distance=float(result.distance),
            )
        )

    if discarded_count or stale_content_count:
        logger.warning(
            "Discarded or corrected inconsistent vector results "
            "for document_id=%d (discarded=%d, stale_content=%d).",
            document_id,
            discarded_count,
            stale_content_count,
        )
    if not verified:
        raise DocumentRetrievalConsistencyError(
            "The vector index is inconsistent with persisted chunks."
        )
    return verified


def _parse_vector_result(
    result: object,
    *,
    document_id: int,
    user_id: int,
) -> int | None:
    vector_id = getattr(result, "id", None)
    content = getattr(result, "content", None)
    metadata = getattr(result, "metadata", None)
    distance = getattr(result, "distance", None)
    if (
        not isinstance(vector_id, str)
        or not isinstance(content, str)
        or not isinstance(metadata, Mapping)
    ):
        return None
    match = _VECTOR_ID_PATTERN.fullmatch(vector_id)
    if match is None:
        return None
    chunk_id = int(match.group(1))
    if (
        not _is_exact_integer(metadata.get("user_id"), user_id)
        or not _is_exact_integer(metadata.get("document_id"), document_id)
        or not _is_exact_integer(metadata.get("chunk_id"), chunk_id)
        or not _is_nonnegative_integer(metadata.get("chunk_index"))
        or isinstance(distance, bool)
        or not isinstance(distance, Real)
        or not isfinite(float(distance))
        or float(distance) < 0
    ):
        return None
    page_number = metadata.get("page_number")
    if page_number is not None and (
        isinstance(page_number, bool)
        or not isinstance(page_number, int)
        or page_number < 1
    ):
        return None
    return chunk_id


def _load_owned_chunks(
    db: Session,
    *,
    chunk_ids: list[int],
    document_id: int,
    user_id: int,
) -> dict[int, DocumentChunk]:
    if not chunk_ids:
        return {}
    statement = (
        select(DocumentChunk)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(
            DocumentChunk.id.in_(chunk_ids),
            DocumentChunk.document_id == document_id,
            Document.user_id == user_id,
            document_not_being_deleted(Document.id),
        )
    )
    try:
        chunks = db.scalars(statement).all()
    except SQLAlchemyError:
        _safe_rollback(db)
        raise DocumentRetrievalInfrastructureError(
            "Persisted chunks could not be verified."
        ) from None
    return {chunk.id: chunk for chunk in chunks}


def _metadata_matches_chunk(
    metadata: Mapping[str, object],
    chunk: DocumentChunk,
) -> bool:
    if not _is_exact_integer(metadata.get("chunk_index"), chunk.chunk_index):
        return False
    page_number = metadata.get("page_number")
    return page_number == chunk.page_number


def _validate_identifier(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise InvalidDocumentRetrievalRequestError(
            f"{name} must be a positive integer."
        )


def _validate_query(query: str) -> str:
    if not isinstance(query, str):
        raise InvalidDocumentRetrievalRequestError(
            "Query must be a string."
        )
    normalized_query = query.strip()
    if not normalized_query:
        raise InvalidDocumentRetrievalRequestError(
            "Query must not be empty."
        )
    if len(normalized_query) > MAX_QUERY_LENGTH:
        raise InvalidDocumentRetrievalRequestError(
            f"Query must not exceed {MAX_QUERY_LENGTH} characters."
        )
    return normalized_query


def _validate_top_k(top_k: int) -> None:
    if (
        isinstance(top_k, bool)
        or not isinstance(top_k, int)
        or top_k < 1
        or top_k > MAX_TOP_K
    ):
        raise InvalidDocumentRetrievalRequestError(
            f"top_k must be between 1 and {MAX_TOP_K}."
        )


def _validate_max_cosine_distance(value: float | None) -> None:
    if value is None:
        return
    if (
        isinstance(value, bool)
        or not isinstance(value, Real)
        or not isfinite(float(value))
        or float(value) < 0
        or float(value) > 2
    ):
        raise InvalidDocumentRetrievalRequestError(
            "max_cosine_distance must be between 0 and 2 when enabled."
        )


def _is_exact_integer(value: object, expected: int) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and value == expected


def _is_nonnegative_integer(value: object) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, int)
        and value >= 0
    )


def _safe_rollback(db: Session) -> None:
    try:
        db.rollback()
    except SQLAlchemyError:
        pass


def _end_read_transaction(db: Session) -> None:
    """Release the read transaction before calling external providers."""

    try:
        db.rollback()
    except SQLAlchemyError:
        raise DocumentRetrievalInfrastructureError(
            "Document state verification could not be completed."
        ) from None
