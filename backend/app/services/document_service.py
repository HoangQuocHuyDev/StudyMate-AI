"""Validation, persistence, and query services for documents."""

from __future__ import annotations

import logging
import stat
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import BinaryIO
from zipfile import BadZipFile, ZipFile

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.document import Document
from app.services.document_deletion import document_not_being_deleted
from app.services.file_storage import (
    EmptyFileError,
    FileSizeLimitExceededError,
    FileStorage,
    FileStorageError,
)


logger = logging.getLogger(__name__)

MAX_DOCX_ENTRIES = 1_000
MAX_DOCX_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
MAX_DOCX_COMPRESSION_RATIO = 100
REQUIRED_DOCX_ENTRIES = frozenset(
    {"[Content_Types].xml", "_rels/.rels", "word/document.xml"}
)
UPLOAD_FILE_TYPES = {
    "pdf": ("PDF", "application/pdf"),
    "docx": (
        "DOCX",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ),
}


class DocumentUploadError(Exception):
    """Base error for document upload processing."""


class InvalidDocumentMetadataError(DocumentUploadError):
    """Raised when filename or title metadata is invalid."""


class UnsupportedDocumentTypeError(DocumentUploadError):
    """Raised when the filename extension is unsupported."""


class EmptyDocumentError(DocumentUploadError):
    """Raised when the uploaded document contains no bytes."""


class DocumentTooLargeError(DocumentUploadError):
    """Raised when the document exceeds the configured byte limit."""


class InvalidDocumentContentError(DocumentUploadError):
    """Raised when bytes do not match the declared document extension."""


class DocumentStorageError(DocumentUploadError):
    """Raised when document bytes cannot be stored safely."""


class DocumentPersistenceError(DocumentUploadError):
    """Raised when document metadata cannot be persisted."""


class DocumentQueryError(Exception):
    """Raised when document metadata cannot be queried safely."""


class OwnedDocumentNotFoundError(DocumentQueryError):
    """Raised when a document is absent or not owned by the caller."""


@dataclass(frozen=True, slots=True)
class ValidatedDocument:
    """Normalized metadata established by server-side validation."""

    title: str
    original_filename: str
    file_type: str
    mime_type: str
    file_size: int


@dataclass(frozen=True, slots=True)
class DocumentListResult:
    """One page of document metadata and its filtered total."""

    items: list[Document]
    total: int


def list_documents(
    db: Session,
    *,
    user_id: int,
    page: int,
    page_size: int,
    search: str | None = None,
    file_type: str | None = None,
) -> DocumentListResult:
    """Return one stable, owner-scoped page without reading stored files."""

    filters = [
        Document.user_id == user_id,
        document_not_being_deleted(Document.id),
    ]
    normalized_search = search.strip() if search is not None else ""
    if normalized_search:
        escaped_search = _escape_like_literal(normalized_search)
        filters.append(
            Document.title.ilike(f"%{escaped_search}%", escape="\\")
        )
    if file_type is not None:
        filters.append(Document.file_type == file_type)

    count_statement = (
        select(func.count())
        .select_from(Document)
        .where(*filters)
    )
    page_statement = (
        select(Document)
        .where(*filters)
        .order_by(Document.created_at.desc(), Document.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )

    try:
        total = db.scalar(count_statement) or 0
        items = list(db.scalars(page_statement).all())
    except SQLAlchemyError as exc:
        try:
            db.rollback()
        except SQLAlchemyError:
            logger.error("Database rollback failed after document query error.")
        raise DocumentQueryError("Could not query document metadata.") from exc

    return DocumentListResult(items=items, total=total)


def get_owned_document(
    db: Session,
    *,
    document_id: int,
    user_id: int,
) -> Document:
    """Return one document only when it belongs to the authenticated owner."""

    if (
        isinstance(document_id, bool)
        or not isinstance(document_id, int)
        or document_id <= 0
        or isinstance(user_id, bool)
        or not isinstance(user_id, int)
        or user_id <= 0
    ):
        raise OwnedDocumentNotFoundError("Document was not found.")

    try:
        document = db.scalar(
            select(Document).where(
                Document.id == document_id,
                Document.user_id == user_id,
                document_not_being_deleted(Document.id),
            )
        )
    except SQLAlchemyError:
        try:
            db.rollback()
        except SQLAlchemyError:
            logger.error("Database rollback failed after document query error.")
        raise DocumentQueryError("Could not query document metadata.") from None

    if document is None:
        raise OwnedDocumentNotFoundError("Document was not found.")
    return document


def validate_document(
    stream: BinaryIO,
    *,
    filename: str | None,
    content_type: str | None,
    title: str | None,
    max_file_size: int,
) -> ValidatedDocument:
    """Validate metadata, size, and basic structure without buffering all bytes."""

    original_filename = _normalize_filename(filename)
    normalized_title = _normalize_title(title, original_filename)
    extension = _get_extension(original_filename)
    file_type, mime_type = UPLOAD_FILE_TYPES[extension]
    _validate_content_type(content_type, expected=mime_type)
    file_size = _get_stream_size(stream)

    if file_size == 0:
        raise EmptyDocumentError("The uploaded file is empty.")
    if file_size > max_file_size:
        raise DocumentTooLargeError("The uploaded file exceeds the size limit.")

    try:
        if extension == "pdf":
            _validate_pdf(stream, file_size)
        elif extension == "docx":
            _validate_docx(stream)
    finally:
        _rewind(stream)

    return ValidatedDocument(
        title=normalized_title,
        original_filename=original_filename,
        file_type=file_type,
        mime_type=mime_type,
        file_size=file_size,
    )


def create_document(
    db: Session,
    storage: FileStorage,
    stream: BinaryIO,
    *,
    filename: str | None,
    content_type: str | None,
    title: str | None,
    user_id: int,
) -> Document:
    """Validate and store bytes, then persist their document metadata."""

    validated = validate_document(
        stream,
        filename=filename,
        content_type=content_type,
        title=title,
        max_file_size=storage.max_file_size,
    )

    try:
        stored_file = storage.save(stream, user_id=user_id)
    except EmptyFileError as exc:
        raise EmptyDocumentError("The uploaded file is empty.") from exc
    except FileSizeLimitExceededError as exc:
        raise DocumentTooLargeError(
            "The uploaded file exceeds the size limit."
        ) from exc
    except FileStorageError as exc:
        raise DocumentStorageError("Could not store document bytes.") from exc

    if stored_file.size != validated.file_size:
        _compensate_file(storage, stored_file.storage_key)
        raise DocumentStorageError("The stored document size changed unexpectedly.")

    document = Document(
        user_id=user_id,
        title=validated.title,
        original_filename=validated.original_filename,
        storage_key=stored_file.storage_key,
        file_type=validated.file_type,
        mime_type=validated.mime_type,
        file_size=stored_file.size,
        status="UPLOADED",
    )

    try:
        db.add(document)
        db.flush()
        db.refresh(document)
        db.commit()
    except SQLAlchemyError as exc:
        try:
            db.rollback()
        except SQLAlchemyError:
            logger.error("Database rollback failed after document upload error.")
        _compensate_file(storage, stored_file.storage_key)
        raise DocumentPersistenceError(
            "Could not persist document metadata."
        ) from exc

    return document


def _escape_like_literal(value: str) -> str:
    """Escape SQL LIKE metacharacters so search text stays literal."""

    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _normalize_filename(filename: str | None) -> str:
    if not isinstance(filename, str):
        raise InvalidDocumentMetadataError("A filename is required.")
    basename = filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if (
        not basename
        or basename in {".", ".."}
        or "\x00" in basename
        or any(ord(character) < 32 for character in basename)
    ):
        raise InvalidDocumentMetadataError("The filename is invalid.")
    if len(basename) > 255:
        raise InvalidDocumentMetadataError("The filename is too long.")
    return basename


def _normalize_title(title: str | None, filename: str) -> str:
    if title is None:
        normalized = filename.rsplit(".", 1)[0].strip()
    elif isinstance(title, str):
        normalized = title.strip()
    else:
        raise InvalidDocumentMetadataError("The title is invalid.")

    if not normalized:
        raise InvalidDocumentMetadataError("The title must not be empty.")
    if len(normalized) > 255:
        raise InvalidDocumentMetadataError("The title is too long.")
    if "\x00" in normalized or any(ord(character) < 32 for character in normalized):
        raise InvalidDocumentMetadataError("The title is invalid.")
    return normalized


def _get_extension(filename: str) -> str:
    if "." not in filename:
        raise UnsupportedDocumentTypeError("The file type is not supported.")
    extension = filename.rsplit(".", 1)[-1].lower()
    if extension not in UPLOAD_FILE_TYPES:
        raise UnsupportedDocumentTypeError("The file type is not supported.")
    return extension


def _validate_content_type(content_type: str | None, *, expected: str) -> None:
    if not isinstance(content_type, str):
        raise UnsupportedDocumentTypeError("The content type is not supported.")
    normalized = content_type.split(";", 1)[0].strip().lower()
    if normalized != expected:
        raise UnsupportedDocumentTypeError("The content type is not supported.")


def _get_stream_size(stream: BinaryIO) -> int:
    try:
        stream.seek(0, 2)
        size = stream.tell()
        stream.seek(0)
    except (OSError, TypeError, ValueError) as exc:
        raise InvalidDocumentContentError(
            "The uploaded file cannot be inspected safely."
        ) from exc
    if not isinstance(size, int) or size < 0:
        raise InvalidDocumentContentError(
            "The uploaded file cannot be inspected safely."
        )
    return size


def _rewind(stream: BinaryIO) -> None:
    try:
        stream.seek(0)
    except (OSError, TypeError, ValueError) as exc:
        raise InvalidDocumentContentError(
            "The uploaded file cannot be rewound safely."
        ) from exc


def _validate_pdf(stream: BinaryIO, file_size: int) -> None:
    try:
        stream.seek(0)
        header = stream.read(8)
        stream.seek(max(0, file_size - 4_096))
        trailer = stream.read(4_096)
    except (OSError, TypeError, ValueError) as exc:
        raise InvalidDocumentContentError("The PDF cannot be inspected.") from exc

    if (
        not isinstance(header, bytes)
        or not header.startswith(b"%PDF-")
        or not isinstance(trailer, bytes)
        or b"startxref" not in trailer
        or b"%%EOF" not in trailer
    ):
        raise InvalidDocumentContentError("The PDF structure is invalid.")


def _validate_docx(stream: BinaryIO) -> None:
    try:
        stream.seek(0)
        with ZipFile(stream) as archive:
            entries = archive.infolist()
            if not entries or len(entries) > MAX_DOCX_ENTRIES:
                raise InvalidDocumentContentError("The DOCX archive is unsafe.")

            names = set()
            total_uncompressed = 0
            total_compressed = 0
            for entry in entries:
                _validate_docx_entry(entry.filename, entry.external_attr)
                if entry.filename in names or entry.flag_bits & 0x1:
                    raise InvalidDocumentContentError("The DOCX archive is unsafe.")
                names.add(entry.filename)
                total_uncompressed += entry.file_size
                total_compressed += entry.compress_size
                if entry.file_size > MAX_DOCX_UNCOMPRESSED_BYTES:
                    raise InvalidDocumentContentError("The DOCX archive is unsafe.")
                if entry.file_size and (
                    entry.compress_size == 0
                    or entry.file_size / entry.compress_size
                    > MAX_DOCX_COMPRESSION_RATIO
                ):
                    raise InvalidDocumentContentError("The DOCX archive is unsafe.")

            if total_uncompressed > MAX_DOCX_UNCOMPRESSED_BYTES:
                raise InvalidDocumentContentError("The DOCX archive is too large.")
            if total_uncompressed and (
                total_compressed == 0
                or total_uncompressed / total_compressed
                > MAX_DOCX_COMPRESSION_RATIO
            ):
                raise InvalidDocumentContentError("The DOCX archive is unsafe.")
            if not REQUIRED_DOCX_ENTRIES.issubset(names):
                raise InvalidDocumentContentError("The DOCX structure is incomplete.")
            if archive.testzip() is not None:
                raise InvalidDocumentContentError("The DOCX archive is corrupted.")
    except InvalidDocumentContentError:
        raise
    except (BadZipFile, OSError, RuntimeError, ValueError) as exc:
        raise InvalidDocumentContentError("The DOCX structure is invalid.") from exc


def _validate_docx_entry(name: str, external_attr: int) -> None:
    normalized_name = name.replace("\\", "/")
    path = PurePosixPath(normalized_name)
    mode = (external_attr >> 16) & 0o170000
    if (
        not normalized_name
        or normalized_name.startswith("/")
        or any(part in {"", ".", ".."} for part in path.parts)
        or stat.S_ISLNK(mode)
    ):
        raise InvalidDocumentContentError("The DOCX archive contains unsafe paths.")


def _compensate_file(
    storage: FileStorage,
    storage_key: str,
) -> None:
    try:
        storage.delete(storage_key)
    except FileStorageError:
        logger.error("event=document_upload_cleanup_failed")
