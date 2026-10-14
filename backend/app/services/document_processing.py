"""Transactional document extraction, chunking, and persistence pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.services.document_chunk_repository import (
    DocumentChunkRepositoryError,
    save_document_chunks,
)
from app.services.document_deletion import document_not_being_deleted
from app.services.document_extractor import (
    ExtractedText,
    extract_document_text,
)
from app.services.file_storage import FileStorage
from app.services.text_chunker import (
    DEFAULT_CHUNK_SIZE,
    MAX_CHUNKS,
    TextChunk,
    chunk_extracted_text,
)


UPLOADED = "UPLOADED"
PROCESSING = "PROCESSING"
READY = "READY"
FAILED = "FAILED"


class DocumentProcessingError(Exception):
    """Base error for controlled document processing failures."""


class DocumentNotFoundError(DocumentProcessingError):
    """Raised when a document is absent or is not owned by the caller."""


class DocumentNotProcessableError(DocumentProcessingError):
    """Raised when a document cannot transition from its current state."""


class DocumentProcessingFailedError(DocumentProcessingError):
    """Raised after document content processing fails and is marked failed."""


class DocumentProcessingInfrastructureError(DocumentProcessingError):
    """Raised when a database operation cannot be confirmed safely."""


class _InvalidProcessingOutputError(DocumentProcessingError):
    """Internal error for an invalid extractor or chunker result."""


@dataclass(frozen=True, slots=True)
class DocumentProcessingResult:
    """Successful processing metadata and chunks persisted by this run."""

    document_id: int
    status: str
    character_count: int
    chunk_count: int
    page_count: int | None
    chunks: tuple[TextChunk, ...]


@dataclass(frozen=True, slots=True)
class DocumentProcessingStatus:
    """Owner-scoped processing metadata safe to expose through the API."""

    document_id: int
    status: str
    rag_status: str
    character_count: int | None
    page_count: int | None
    processed_at: datetime | None
    indexed_at: datetime | None
    chunk_count: int


@dataclass(frozen=True, slots=True)
class _ClaimedDocument:
    document_id: int
    storage_key: str
    file_type: str


def process_document(
    db: Session,
    storage: FileStorage,
    *,
    document_id: int,
    user_id: int,
) -> DocumentProcessingResult:
    """Atomically claim, extract, chunk, and finalize one owned document."""

    _validate_identifier(document_id, "document_id")
    _validate_identifier(user_id, "user_id")
    claimed = _claim_document(
        db,
        document_id=document_id,
        user_id=user_id,
    )
    return _process_claimed_document(
        db,
        storage,
        claimed=claimed,
        user_id=user_id,
    )


def retry_document(
    db: Session,
    storage: FileStorage,
    *,
    document_id: int,
    user_id: int,
) -> DocumentProcessingResult:
    """Intentionally retry an owned FAILED or chunkless READY document."""

    _validate_identifier(document_id, "document_id")
    _validate_identifier(user_id, "user_id")
    claimed = _claim_retryable_document(
        db,
        document_id=document_id,
        user_id=user_id,
    )
    return _process_claimed_document(
        db,
        storage,
        claimed=claimed,
        user_id=user_id,
    )


def get_document_processing_status(
    db: Session,
    *,
    document_id: int,
    user_id: int,
) -> DocumentProcessingStatus:
    """Return processing state and persisted chunk count for one owned document."""

    _validate_identifier(document_id, "document_id")
    _validate_identifier(user_id, "user_id")
    chunk_count = (
        select(func.count())
        .select_from(DocumentChunk)
        .where(DocumentChunk.document_id == Document.id)
        .correlate(Document)
        .scalar_subquery()
    )
    statement = select(
        Document.id.label("document_id"),
        Document.status,
        Document.rag_status,
        Document.character_count,
        Document.page_count,
        Document.processed_at,
        Document.indexed_at,
        chunk_count.label("chunk_count"),
    ).where(
        Document.id == document_id,
        Document.user_id == user_id,
        document_not_being_deleted(Document.id),
    )

    try:
        row = db.execute(statement).mappings().one_or_none()
    except SQLAlchemyError:
        _safe_rollback(db)
        raise DocumentProcessingInfrastructureError(
            "Document processing status could not be queried."
        ) from None
    if row is None:
        db.rollback()
        raise DocumentNotFoundError("Document was not found.")
    return DocumentProcessingStatus(**row)


def _process_claimed_document(
    db: Session,
    storage: FileStorage,
    *,
    claimed: _ClaimedDocument,
    user_id: int,
) -> DocumentProcessingResult:
    """Extract, chunk, and finalize a document after a committed claim."""

    try:
        extracted = extract_document_text(
            storage,
            storage_key=claimed.storage_key,
            file_type=claimed.file_type,
        )
        chunks = chunk_extracted_text(extracted)
        _validate_processing_output(extracted, chunks)
    except Exception:
        _mark_failed(db, document_id=claimed.document_id, user_id=user_id)
        raise DocumentProcessingFailedError(
            "Document content could not be processed."
        ) from None

    _persist_chunks_and_mark_ready(
        db,
        document_id=claimed.document_id,
        user_id=user_id,
        extracted=extracted,
        chunks=chunks,
    )
    return DocumentProcessingResult(
        document_id=claimed.document_id,
        status=READY,
        character_count=extracted.character_count,
        chunk_count=len(chunks),
        page_count=extracted.page_count,
        chunks=tuple(chunks),
    )


def _validate_identifier(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise DocumentNotFoundError(f"{name} does not identify a document.")


def _claim_document(
    db: Session,
    *,
    document_id: int,
    user_id: int,
) -> _ClaimedDocument:
    statement = (
        update(Document)
        .where(
            Document.id == document_id,
            Document.user_id == user_id,
            Document.status == UPLOADED,
            document_not_being_deleted(Document.id),
        )
        .values(status=PROCESSING, updated_at=func.current_timestamp())
        .returning(Document.id, Document.storage_key, Document.file_type)
        .execution_options(synchronize_session=False)
    )

    try:
        claimed_row = db.execute(statement).mappings().one_or_none()
        if claimed_row is None:
            current_status = db.scalar(
                select(Document.status).where(
                    Document.id == document_id,
                    Document.user_id == user_id,
                    document_not_being_deleted(Document.id),
                )
            )
            db.rollback()
            if current_status is None:
                raise DocumentNotFoundError("Document was not found.")
            raise DocumentNotProcessableError(
                "Document is not in a processable state."
            )

        claimed = _ClaimedDocument(
            document_id=claimed_row["id"],
            storage_key=claimed_row["storage_key"],
            file_type=claimed_row["file_type"],
        )
        db.commit()
        return claimed
    except (DocumentNotFoundError, DocumentNotProcessableError):
        raise
    except SQLAlchemyError:
        _safe_rollback(db)
        raise DocumentProcessingInfrastructureError(
            "Document processing state could not be claimed."
        ) from None


def _claim_retryable_document(
    db: Session,
    *,
    document_id: int,
    user_id: int,
) -> _ClaimedDocument:
    no_persisted_chunks = ~select(DocumentChunk.id).where(
        DocumentChunk.document_id == Document.id
    ).exists()
    statement = (
        update(Document)
        .where(
            Document.id == document_id,
            Document.user_id == user_id,
            Document.status.in_((FAILED, READY)),
            no_persisted_chunks,
            document_not_being_deleted(Document.id),
        )
        .values(status=PROCESSING, updated_at=func.current_timestamp())
        .returning(Document.id, Document.storage_key, Document.file_type)
        .execution_options(synchronize_session=False)
    )

    try:
        claimed_row = db.execute(statement).mappings().one_or_none()
        if claimed_row is None:
            current_status = db.scalar(
                select(Document.status).where(
                    Document.id == document_id,
                    Document.user_id == user_id,
                    document_not_being_deleted(Document.id),
                )
            )
            db.rollback()
            if current_status is None:
                raise DocumentNotFoundError("Document was not found.")
            raise DocumentNotProcessableError(
                "Document is not safely retryable."
            )

        claimed = _ClaimedDocument(
            document_id=claimed_row["id"],
            storage_key=claimed_row["storage_key"],
            file_type=claimed_row["file_type"],
        )
        db.commit()
        return claimed
    except (DocumentNotFoundError, DocumentNotProcessableError):
        raise
    except SQLAlchemyError:
        _safe_rollback(db)
        raise DocumentProcessingInfrastructureError(
            "Document retry state could not be claimed."
        ) from None


def _persist_chunks_and_mark_ready(
    db: Session,
    *,
    document_id: int,
    user_id: int,
    extracted: ExtractedText,
    chunks: list[TextChunk],
) -> None:
    statement = (
        update(Document)
        .where(
            Document.id == document_id,
            Document.user_id == user_id,
            Document.status == PROCESSING,
            document_not_being_deleted(Document.id),
        )
        .values(
            character_count=extracted.character_count,
            page_count=extracted.page_count,
            processed_at=func.current_timestamp(),
            status=READY,
            updated_at=func.current_timestamp(),
        )
        .returning(Document.id)
        .execution_options(synchronize_session=False)
    )
    try:
        save_document_chunks(
            db,
            document_id=document_id,
            user_id=user_id,
            chunks=chunks,
        )
        transitioned_id = db.scalar(statement)
        if transitioned_id is None:
            db.rollback()
            raise DocumentProcessingInfrastructureError(
                "Document completion state could not be saved."
            )
        db.commit()
    except DocumentProcessingInfrastructureError:
        raise
    except (DocumentChunkRepositoryError, SQLAlchemyError):
        _safe_rollback(db)
        raise DocumentProcessingInfrastructureError(
            "Document chunks and completion state could not be saved."
        ) from None


def _mark_failed(db: Session, *, document_id: int, user_id: int) -> None:
    _commit_transition(
        db,
        document_id=document_id,
        user_id=user_id,
        expected_status=PROCESSING,
        next_status=FAILED,
        failure_message="Document failure state could not be saved.",
    )


def _commit_transition(
    db: Session,
    *,
    document_id: int,
    user_id: int,
    expected_status: str,
    next_status: str,
    failure_message: str,
) -> None:
    statement = (
        update(Document)
        .where(
            Document.id == document_id,
            Document.user_id == user_id,
            Document.status == expected_status,
        )
        .values(status=next_status, updated_at=func.current_timestamp())
        .returning(Document.id)
        .execution_options(synchronize_session=False)
    )
    try:
        transitioned_id = db.scalar(statement)
        if transitioned_id is None:
            db.rollback()
            raise DocumentProcessingInfrastructureError(failure_message)
        db.commit()
    except DocumentProcessingInfrastructureError:
        raise
    except SQLAlchemyError:
        _safe_rollback(db)
        raise DocumentProcessingInfrastructureError(failure_message) from None


def _validate_processing_output(
    extracted: ExtractedText,
    chunks: list[TextChunk],
) -> None:
    text = extracted.text
    if (
        extracted.character_count <= 0
        or extracted.character_count != len(text)
        or not chunks
        or len(chunks) > MAX_CHUNKS
    ):
        raise _InvalidProcessingOutputError(
            "Document chunk output is invalid."
        )

    covered_until = 0
    for expected_index, chunk in enumerate(chunks):
        valid_chunk = (
            chunk.index == expected_index
            and 0 <= chunk.start_char < chunk.end_char <= len(text)
            and chunk.character_count == len(chunk.text)
            and chunk.character_count <= DEFAULT_CHUNK_SIZE
            and text[chunk.start_char : chunk.end_char] == chunk.text
        )
        if not valid_chunk:
            raise _InvalidProcessingOutputError(
                "Document chunk output is invalid."
            )
        if chunk.start_char > covered_until and text[
            covered_until : chunk.start_char
        ].strip():
            raise _InvalidProcessingOutputError(
                "Document chunk output is incomplete."
            )
        covered_until = max(covered_until, chunk.end_char)

    if text[covered_until:].strip():
        raise _InvalidProcessingOutputError(
            "Document chunk output is incomplete."
        )


def _safe_rollback(db: Session) -> None:
    try:
        db.rollback()
    except SQLAlchemyError:
        pass
