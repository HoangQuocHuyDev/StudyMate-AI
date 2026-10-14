"""SQLAlchemy repository for persistent document text chunks."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, insert, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.services.document_deletion import document_not_being_deleted
from app.services.text_chunker import TextChunk


class DocumentChunkRepositoryError(Exception):
    """Base error for controlled document chunk persistence failures."""


class InvalidDocumentChunkError(DocumentChunkRepositoryError, ValueError):
    """Raised before persistence when chunk metadata is invalid."""


class DocumentChunkDocumentNotFoundError(DocumentChunkRepositoryError):
    """Raised when a target document is absent or not owned by the caller."""


class DuplicateDocumentChunksError(DocumentChunkRepositoryError):
    """Raised when a document already has persistent chunks."""


class DocumentChunkPersistenceError(DocumentChunkRepositoryError):
    """Raised when chunks cannot be inserted atomically."""


class DocumentChunkQueryError(DocumentChunkRepositoryError):
    """Raised when persisted chunks cannot be queried safely."""


def save_document_chunks(
    db: Session,
    *,
    document_id: int,
    user_id: int,
    chunks: Sequence[TextChunk],
) -> int:
    """Bulk insert chunks for one owner without committing the transaction."""

    _validate_document_id(document_id)
    _validate_user_id(user_id)
    chunk_values = tuple(chunks)
    _validate_chunks(chunk_values)

    try:
        document_exists = db.scalar(
            select(Document.id)
            .where(
                Document.id == document_id,
                Document.user_id == user_id,
                document_not_being_deleted(Document.id),
            )
            .with_for_update()
        )
        if document_exists is None:
            raise DocumentChunkDocumentNotFoundError(
                "Document was not found."
            )

        existing_count = db.scalar(
            select(func.count())
            .select_from(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
        ) or 0
        if existing_count:
            raise DuplicateDocumentChunksError(
                "Document chunks already exist."
            )

        db.execute(
            insert(DocumentChunk),
            [
                {
                    "document_id": document_id,
                    "chunk_index": chunk.index,
                    "content": chunk.text,
                    "start_char": chunk.start_char,
                    "end_char": chunk.end_char,
                    "character_count": chunk.character_count,
                    "page_number": chunk.page_number,
                }
                for chunk in chunk_values
            ],
        )
    except (
        DocumentChunkDocumentNotFoundError,
        DuplicateDocumentChunksError,
    ):
        raise
    except SQLAlchemyError:
        raise DocumentChunkPersistenceError(
            "Document chunks could not be saved."
        ) from None

    return len(chunk_values)


def get_document_chunks(
    db: Session,
    *,
    document_id: int,
    user_id: int,
) -> list[DocumentChunk]:
    """Return an owned document's chunks in stable source order."""

    _validate_document_id(document_id)
    _validate_user_id(user_id)
    try:
        return list(
            db.scalars(
                select(DocumentChunk)
                .join(Document, Document.id == DocumentChunk.document_id)
                .where(
                    DocumentChunk.document_id == document_id,
                    Document.user_id == user_id,
                    document_not_being_deleted(Document.id),
                )
                .order_by(DocumentChunk.chunk_index)
            ).all()
        )
    except SQLAlchemyError:
        raise DocumentChunkQueryError(
            "Document chunks could not be queried."
        ) from None


def count_document_chunks(
    db: Session,
    *,
    document_id: int,
    user_id: int,
) -> int:
    """Count persistent chunks belonging to one owned document."""

    _validate_document_id(document_id)
    _validate_user_id(user_id)
    try:
        return db.scalar(
            select(func.count())
            .select_from(DocumentChunk)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(
                DocumentChunk.document_id == document_id,
                Document.user_id == user_id,
                document_not_being_deleted(Document.id),
            )
        ) or 0
    except SQLAlchemyError:
        raise DocumentChunkQueryError(
            "Document chunks could not be counted."
        ) from None


def _validate_document_id(document_id: int) -> None:
    if (
        isinstance(document_id, bool)
        or not isinstance(document_id, int)
        or document_id <= 0
    ):
        raise InvalidDocumentChunkError(
            "document_id must be a positive integer."
        )


def _validate_user_id(user_id: int) -> None:
    if (
        isinstance(user_id, bool)
        or not isinstance(user_id, int)
        or user_id <= 0
    ):
        raise InvalidDocumentChunkError(
            "user_id must be a positive integer."
        )


def _validate_chunks(chunks: tuple[TextChunk, ...]) -> None:
    if not chunks:
        raise InvalidDocumentChunkError("At least one chunk is required.")

    for expected_index, chunk in enumerate(chunks):
        if not isinstance(chunk, TextChunk):
            raise InvalidDocumentChunkError("Chunk metadata is invalid.")
        if (
            isinstance(chunk.index, bool)
            or chunk.index != expected_index
            or not chunk.text
            or isinstance(chunk.start_char, bool)
            or chunk.start_char < 0
            or isinstance(chunk.end_char, bool)
            or chunk.end_char <= chunk.start_char
            or isinstance(chunk.character_count, bool)
            or chunk.character_count != len(chunk.text)
            or chunk.character_count != chunk.end_char - chunk.start_char
            or (
                chunk.page_number is not None
                and (
                    isinstance(chunk.page_number, bool)
                    or not isinstance(chunk.page_number, int)
                    or chunk.page_number < 1
                )
            )
        ):
            raise InvalidDocumentChunkError("Chunk metadata is invalid.")
