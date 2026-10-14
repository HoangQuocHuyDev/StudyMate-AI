"""Owner-scoped orchestration for indexing persisted document chunks."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
import json
import logging
from math import ceil
from time import perf_counter
from typing import Protocol

from sqlalchemy import func, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.services.document_chunk_repository import (
    DocumentChunkRepositoryError,
    get_document_chunks,
)
from app.services.document_deletion import document_not_being_deleted
from app.services.rag.chroma_vector_store import (
    ChromaOpenError,
    ChunkVectorRecord,
    IncompatibleChromaCollectionError,
)
from app.services.rag.embedding_service import (
    EmbeddingProvider,
    GeminiEmbeddingError,
)


DOCUMENT_READY = "READY"
RAG_PENDING = "PENDING"
RAG_INDEXING = "INDEXING"
RAG_READY = "READY"
RAG_FAILED = "FAILED"
DEFAULT_EMBEDDING_BATCH_SIZE = 32
MAX_EMBEDDING_BATCH_SIZE = 100
logger = logging.getLogger(__name__)


class DocumentVectorStore(Protocol):
    """Vector-store operations required by document indexing."""

    def upsert_chunks(self, records: Sequence[ChunkVectorRecord]) -> int:
        """Idempotently persist chunk vectors."""

    def get_document_vector_ids(
        self,
        *,
        user_id: int,
        document_id: int,
    ) -> set[str]:
        """Return exact IDs currently indexed for one owned document."""


class DocumentIndexingError(Exception):
    """Base error for controlled document indexing failures."""


class DocumentIndexingNotFoundError(DocumentIndexingError):
    """Raised when a document is absent or not owned by the caller."""


class DocumentNotIndexableError(DocumentIndexingError):
    """Raised when a document cannot be atomically claimed."""


class DocumentIndexingFailedError(DocumentIndexingError):
    """Raised after an external indexing failure is recorded safely."""


class DocumentIndexingInfrastructureError(DocumentIndexingError):
    """Raised when PostgreSQL state cannot be confirmed safely."""


@dataclass(frozen=True, slots=True)
class DocumentIndexingResult:
    """Safe result returned after exact vector-set verification."""

    document_id: int
    rag_status: str
    vector_count: int
    indexed_at: datetime


@dataclass(frozen=True, slots=True)
class DocumentRagStatus:
    """PostgreSQL-backed RAG state for one owned document."""

    document_id: int
    status: str
    rag_status: str
    chunk_count: int
    indexed_at: datetime | None
    can_index: bool


@dataclass(frozen=True, slots=True)
class _IndexableChunk:
    id: int
    chunk_index: int
    content: str
    page_number: int | None


@dataclass(frozen=True, slots=True)
class _IndexingFailureDetails:
    stage: str
    batch_index: int | None
    total_batches: int
    chunk_count: int
    error_code: str
    provider_http_status: int | None
    failure_phase: str | None
    exception_type: str | None


class _IndexingStageError(Exception):
    """Carry only diagnostic-safe failure metadata across the orchestrator."""

    def __init__(self, details: _IndexingFailureDetails) -> None:
        super().__init__(details.error_code)
        self.details = details


def get_document_rag_status(
    db: Session,
    *,
    document_id: int,
    user_id: int,
) -> DocumentRagStatus:
    """Return owner-scoped indexing state without consulting ChromaDB."""

    _validate_identifier(document_id, "document_id")
    _validate_identifier(user_id, "user_id")
    chunk_count = (
        select(func.count(DocumentChunk.id))
        .where(DocumentChunk.document_id == Document.id)
        .correlate(Document)
        .scalar_subquery()
    )
    statement = select(
        Document.id,
        Document.status,
        Document.rag_status,
        Document.indexed_at,
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
        raise DocumentIndexingInfrastructureError(
            "Document indexing status could not be loaded."
        ) from None
    if row is None:
        raise DocumentIndexingNotFoundError("Document was not found.")

    count = int(row.chunk_count)
    can_index = (
        row.status == DOCUMENT_READY
        and count > 0
        and row.rag_status in (RAG_PENDING, RAG_FAILED)
    )
    return DocumentRagStatus(
        document_id=row.id,
        status=row.status,
        rag_status=row.rag_status,
        chunk_count=count,
        indexed_at=row.indexed_at,
        can_index=can_index,
    )


def index_document(
    db: Session,
    embedder: EmbeddingProvider,
    vector_store: DocumentVectorStore,
    *,
    document_id: int,
    user_id: int,
    batch_size: int = DEFAULT_EMBEDDING_BATCH_SIZE,
) -> DocumentIndexingResult:
    """Claim and index one processed document without a distributed transaction."""

    _validate_identifier(document_id, "document_id")
    _validate_identifier(user_id, "user_id")
    _validate_batch_size(batch_size)
    _claim_document(db, document_id=document_id, user_id=user_id)
    chunks = _load_claimed_chunks(
        db,
        document_id=document_id,
        user_id=user_id,
    )
    if not chunks:
        _mark_failed(db, document_id=document_id, user_id=user_id)
        raise DocumentIndexingFailedError(
            "Document chunks are unavailable for indexing."
        )

    expected_ids = {f"document_chunk:{chunk.id}" for chunk in chunks}
    total_batches = ceil(len(chunks) / batch_size)
    indexing_started = perf_counter()
    try:
        for batch_offset, start in enumerate(
            range(0, len(chunks), batch_size),
            start=1,
        ):
            batch = chunks[start : start + batch_size]
            embeddings = _embed_batch(
                embedder,
                batch,
                document_id=document_id,
                batch_index=batch_offset,
                total_batches=total_batches,
                chunk_count=len(chunks),
            )
            records = [
                ChunkVectorRecord(
                    id=f"document_chunk:{chunk.id}",
                    embedding=embedding,
                    content=chunk.content,
                    metadata={
                        "user_id": user_id,
                        "document_id": document_id,
                        "chunk_id": chunk.id,
                        "chunk_index": chunk.chunk_index,
                        **(
                            {"page_number": chunk.page_number}
                            if chunk.page_number is not None
                            else {}
                        ),
                    },
                )
                for chunk, embedding in zip(batch, embeddings, strict=True)
            ]
            persisted_count = _upsert_batch(
                vector_store,
                records,
                document_id=document_id,
                batch_index=batch_offset,
                total_batches=total_batches,
                chunk_count=len(chunks),
            )

        _verify_vectors(
            vector_store,
            expected_ids,
            user_id=user_id,
            document_id=document_id,
            total_batches=total_batches,
            chunk_count=len(chunks),
        )
    except _IndexingStageError as exc:
        _mark_failed(db, document_id=document_id, user_id=user_id)
        _log_indexing_event(
            logging.WARNING,
            "document_indexing_failed",
            document_id=document_id,
            details=exc.details,
            stage="indexing_failed",
            elapsed_ms=_elapsed_ms(indexing_started),
        )
        raise DocumentIndexingFailedError(
            "Document vectors could not be indexed."
        ) from None
    except Exception:
        details = _failure_details(
            stage="indexing",
            batch_index=None,
            total_batches=total_batches,
            chunk_count=len(chunks),
            error_code="indexing_failed",
        )
        _mark_failed(db, document_id=document_id, user_id=user_id)
        _log_indexing_event(
            logging.WARNING,
            "document_indexing_failed",
            document_id=document_id,
            details=details,
            stage="indexing_failed",
            elapsed_ms=_elapsed_ms(indexing_started),
        )
        raise DocumentIndexingFailedError(
            "Document vectors could not be indexed."
        ) from None

    return _mark_ready(
        db,
        document_id=document_id,
        user_id=user_id,
        vector_count=len(expected_ids),
    )


def _claim_document(db: Session, *, document_id: int, user_id: int) -> None:
    chunks_exist = select(DocumentChunk.id).where(
        DocumentChunk.document_id == Document.id
    ).exists()
    statement = (
        update(Document)
        .where(
            Document.id == document_id,
            Document.user_id == user_id,
            Document.status == DOCUMENT_READY,
            Document.rag_status.in_((RAG_PENDING, RAG_FAILED)),
            chunks_exist,
            document_not_being_deleted(Document.id),
        )
        .values(
            rag_status=RAG_INDEXING,
            indexed_at=None,
            updated_at=func.current_timestamp(),
        )
        .returning(Document.id)
        .execution_options(synchronize_session=False)
    )
    try:
        claimed_id = db.scalar(statement)
        if claimed_id is None:
            exists_for_owner = db.scalar(
                select(Document.id).where(
                    Document.id == document_id,
                    Document.user_id == user_id,
                    document_not_being_deleted(Document.id),
                )
            )
            db.rollback()
            if exists_for_owner is None:
                raise DocumentIndexingNotFoundError(
                    "Document was not found."
                )
            raise DocumentNotIndexableError(
                "Document is not in an indexable state."
            )
        db.commit()
    except (DocumentIndexingNotFoundError, DocumentNotIndexableError):
        raise
    except SQLAlchemyError:
        _safe_rollback(db)
        raise DocumentIndexingInfrastructureError(
            "Document indexing state could not be claimed."
        ) from None


def _load_claimed_chunks(
    db: Session,
    *,
    document_id: int,
    user_id: int,
) -> tuple[_IndexableChunk, ...]:
    try:
        stored_chunks = get_document_chunks(
            db,
            document_id=document_id,
            user_id=user_id,
        )
        chunks = tuple(
            _IndexableChunk(
                id=chunk.id,
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                page_number=chunk.page_number,
            )
            for chunk in stored_chunks
            if chunk.content.strip()
        )
        db.rollback()
        return chunks
    except (DocumentChunkRepositoryError, SQLAlchemyError):
        _safe_rollback(db)
        raise DocumentIndexingInfrastructureError(
            "Document chunks could not be loaded for indexing."
        ) from None


def _mark_ready(
    db: Session,
    *,
    document_id: int,
    user_id: int,
    vector_count: int,
) -> DocumentIndexingResult:
    statement = (
        update(Document)
        .where(
            Document.id == document_id,
            Document.user_id == user_id,
            Document.status == DOCUMENT_READY,
            Document.rag_status == RAG_INDEXING,
        )
        .values(
            rag_status=RAG_READY,
            indexed_at=func.current_timestamp(),
            updated_at=func.current_timestamp(),
        )
        .returning(Document.indexed_at)
        .execution_options(synchronize_session=False)
    )
    try:
        indexed_at = db.scalar(statement)
        if indexed_at is None:
            db.rollback()
            raise DocumentIndexingInfrastructureError(
                "Document indexing completion could not be saved."
            )
        db.commit()
        return DocumentIndexingResult(
            document_id=document_id,
            rag_status=RAG_READY,
            vector_count=vector_count,
            indexed_at=indexed_at,
        )
    except DocumentIndexingInfrastructureError:
        raise
    except SQLAlchemyError:
        _safe_rollback(db)
        raise DocumentIndexingInfrastructureError(
            "Document indexing completion could not be saved."
        ) from None


def _mark_failed(db: Session, *, document_id: int, user_id: int) -> None:
    statement = (
        update(Document)
        .where(
            Document.id == document_id,
            Document.user_id == user_id,
            Document.status == DOCUMENT_READY,
            Document.rag_status == RAG_INDEXING,
        )
        .values(
            rag_status=RAG_FAILED,
            indexed_at=None,
            updated_at=func.current_timestamp(),
        )
        .returning(Document.id)
        .execution_options(synchronize_session=False)
    )
    try:
        transitioned_id = db.scalar(statement)
        if transitioned_id is None:
            db.rollback()
            raise DocumentIndexingInfrastructureError(
                "Document indexing failure state could not be saved."
            )
        db.commit()
    except DocumentIndexingInfrastructureError:
        raise
    except SQLAlchemyError:
        _safe_rollback(db)
        raise DocumentIndexingInfrastructureError(
            "Document indexing failure state could not be saved."
        ) from None


def _validate_identifier(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise DocumentIndexingNotFoundError(
            f"{name} does not identify a document."
        )


def _validate_batch_size(batch_size: int) -> None:
    if (
        isinstance(batch_size, bool)
        or not isinstance(batch_size, int)
        or batch_size < 1
        or batch_size > MAX_EMBEDDING_BATCH_SIZE
    ):
        raise ValueError(
            f"batch_size must be between 1 and {MAX_EMBEDDING_BATCH_SIZE}."
        )


def _embed_batch(
    embedder: EmbeddingProvider,
    batch: Sequence[_IndexableChunk],
    *,
    document_id: int,
    batch_index: int,
    total_batches: int,
    chunk_count: int,
) -> list[list[float]]:
    started = perf_counter()
    try:
        embeddings = embedder.embed_documents([chunk.content for chunk in batch])
    except Exception as exc:
        (
            error_code,
            provider_http_status,
            failure_phase,
            exception_type,
            provider_elapsed_ms,
        ) = _classify_embedding_error(exc)
        details = _failure_details(
            stage="embedding_batch",
            batch_index=batch_index,
            total_batches=total_batches,
            chunk_count=chunk_count,
            error_code=error_code,
            provider_http_status=provider_http_status,
            failure_phase=failure_phase,
            exception_type=exception_type,
        )
        _log_indexing_event(
            logging.WARNING,
            "document_indexing_stage_failed",
            document_id=document_id,
            details=details,
            elapsed_ms=(
                provider_elapsed_ms
                if provider_elapsed_ms is not None
                else _elapsed_ms(started)
            ),
            batch_chunk_count=len(batch),
        )
        raise _IndexingStageError(details) from None
    if not isinstance(embeddings, list) or len(embeddings) != len(batch):
        details = _failure_details(
            stage="embedding_batch",
            batch_index=batch_index,
            total_batches=total_batches,
            chunk_count=chunk_count,
            error_code="gemini_invalid_response",
        )
        _log_indexing_event(
            logging.WARNING,
            "document_indexing_stage_failed",
            document_id=document_id,
            details=details,
            elapsed_ms=_elapsed_ms(started),
            batch_chunk_count=len(batch),
        )
        raise _IndexingStageError(details)
    _log_indexing_event(
        logging.INFO,
        "document_indexing_stage_completed",
        document_id=document_id,
        details=_failure_details(
            stage="embedding_batch",
            batch_index=batch_index,
            total_batches=total_batches,
            chunk_count=chunk_count,
            error_code="none",
        ),
        elapsed_ms=_elapsed_ms(started),
        batch_chunk_count=len(batch),
    )
    return embeddings


def _upsert_batch(
    vector_store: DocumentVectorStore,
    records: Sequence[ChunkVectorRecord],
    *,
    document_id: int,
    batch_index: int,
    total_batches: int,
    chunk_count: int,
) -> int:
    started = perf_counter()
    try:
        persisted_count = vector_store.upsert_chunks(records)
    except Exception as exc:
        details = _failure_details(
            stage="chroma_upsert_batch",
            batch_index=batch_index,
            total_batches=total_batches,
            chunk_count=chunk_count,
            error_code=_classify_chroma_error(exc, "chroma_upsert_failed"),
        )
        _log_indexing_event(
            logging.WARNING,
            "document_indexing_stage_failed",
            document_id=document_id,
            details=details,
            elapsed_ms=_elapsed_ms(started),
            batch_chunk_count=len(records),
        )
        raise _IndexingStageError(details) from None
    if persisted_count != len(records):
        details = _failure_details(
            stage="chroma_upsert_batch",
            batch_index=batch_index,
            total_batches=total_batches,
            chunk_count=chunk_count,
            error_code="chroma_upsert_failed",
        )
        _log_indexing_event(
            logging.WARNING,
            "document_indexing_stage_failed",
            document_id=document_id,
            details=details,
            elapsed_ms=_elapsed_ms(started),
            batch_chunk_count=len(records),
        )
        raise _IndexingStageError(details)
    _log_indexing_event(
        logging.INFO,
        "document_indexing_stage_completed",
        document_id=document_id,
        details=_failure_details(
            stage="chroma_upsert_batch",
            batch_index=batch_index,
            total_batches=total_batches,
            chunk_count=chunk_count,
            error_code="none",
        ),
        elapsed_ms=_elapsed_ms(started),
        batch_chunk_count=len(records),
    )
    return persisted_count


def _verify_vectors(
    vector_store: DocumentVectorStore,
    expected_ids: set[str],
    *,
    user_id: int,
    document_id: int,
    total_batches: int,
    chunk_count: int,
) -> None:
    started = perf_counter()
    try:
        actual_ids = vector_store.get_document_vector_ids(
            user_id=user_id,
            document_id=document_id,
        )
    except Exception as exc:
        details = _failure_details(
            stage="vector_verification",
            batch_index=None,
            total_batches=total_batches,
            chunk_count=chunk_count,
            error_code=_classify_chroma_error(exc, "chroma_verify_failed"),
        )
        _log_indexing_event(
            logging.WARNING,
            "document_indexing_stage_failed",
            document_id=document_id,
            details=details,
            elapsed_ms=_elapsed_ms(started),
        )
        raise _IndexingStageError(details) from None
    if actual_ids != expected_ids:
        details = _failure_details(
            stage="vector_verification",
            batch_index=None,
            total_batches=total_batches,
            chunk_count=chunk_count,
            error_code="vector_id_mismatch",
        )
        _log_indexing_event(
            logging.WARNING,
            "document_indexing_stage_failed",
            document_id=document_id,
            details=details,
            elapsed_ms=_elapsed_ms(started),
        )
        raise _IndexingStageError(details)
    _log_indexing_event(
        logging.INFO,
        "document_indexing_stage_completed",
        document_id=document_id,
        details=_failure_details(
            stage="vector_verification",
            batch_index=None,
            total_batches=total_batches,
            chunk_count=chunk_count,
            error_code="none",
        ),
        elapsed_ms=_elapsed_ms(started),
    )


def _classify_embedding_error(
    error: Exception,
) -> tuple[str, int | None, str | None, str | None, float | None]:
    if isinstance(error, GeminiEmbeddingError):
        return (
            error.error_code,
            error.provider_http_status,
            error.failure_phase,
            error.exception_type,
            error.elapsed_ms,
        )
    return "gemini_request_failed", None, None, None, None


def _classify_chroma_error(error: Exception, fallback: str) -> str:
    if isinstance(error, ChromaOpenError):
        return "chroma_open_failed"
    if isinstance(error, IncompatibleChromaCollectionError):
        return "chroma_incompatible_collection"
    return fallback


def _failure_details(
    *,
    stage: str,
    batch_index: int | None,
    total_batches: int,
    chunk_count: int,
    error_code: str,
    provider_http_status: int | None = None,
    failure_phase: str | None = None,
    exception_type: str | None = None,
) -> _IndexingFailureDetails:
    return _IndexingFailureDetails(
        stage=stage,
        batch_index=batch_index,
        total_batches=total_batches,
        chunk_count=chunk_count,
        error_code=error_code,
        provider_http_status=provider_http_status,
        failure_phase=failure_phase,
        exception_type=exception_type,
    )


def _log_indexing_event(
    level: int,
    message: str,
    *,
    document_id: int,
    details: _IndexingFailureDetails,
    elapsed_ms: float,
    stage: str | None = None,
    batch_chunk_count: int | None = None,
) -> None:
    event = {
        "event": message,
        "document_id": document_id,
        "stage": stage or details.stage,
        "failed_stage": details.stage if stage is not None else None,
        "batch_index": details.batch_index,
        "total_batches": details.total_batches,
        "chunk_count": details.chunk_count,
        "batch_chunk_count": batch_chunk_count,
        "error_code": details.error_code,
        "failure_phase": details.failure_phase,
        "exception_type": details.exception_type,
        "provider_http_status": details.provider_http_status,
        "elapsed_ms": elapsed_ms,
    }
    logger.log(
        level,
        json.dumps(event, ensure_ascii=False, separators=(",", ":")),
        extra=event,
    )


def _elapsed_ms(started: float) -> float:
    return round(max(0.0, (perf_counter() - started) * 1000), 3)


def _safe_rollback(db: Session) -> None:
    try:
        db.rollback()
    except SQLAlchemyError:
        pass
