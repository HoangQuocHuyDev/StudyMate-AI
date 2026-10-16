"""Read-only plain-text previews for owned DOCX documents."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.services.document_extractor import (
    DEFAULT_MAX_CHARACTERS,
    DocumentExtractionError,
    DocumentExtractionLimitError,
    EmptyDocumentTextError,
    extract_document_text,
)
from app.services.document_service import (
    DocumentQueryError,
    OwnedDocumentNotFoundError,
    get_owned_document,
)
from app.services.file_storage import FileStorage


class DocumentPreviewError(Exception):
    """Base error for controlled document preview failures."""


class DocumentPreviewNotFoundError(DocumentPreviewError):
    """Raised when an owned, live document cannot be found."""


class UnsupportedDocumentPreviewError(DocumentPreviewError):
    """Raised when the requested document is not a DOCX file."""


class DocumentPreviewTooLargeError(DocumentPreviewError):
    """Raised when extracted text exceeds the established safety limit."""


class DocumentPreviewUnavailableError(DocumentPreviewError):
    """Raised when source bytes cannot be read or parsed safely."""


@dataclass(frozen=True, slots=True)
class DocumentPreview:
    """Safe plain-text preview metadata returned to an owner."""

    document_id: int
    title: str
    original_filename: str
    file_type: str
    content: str
    character_count: int


def get_owned_docx_preview(
    db: Session,
    storage: FileStorage,
    *,
    document_id: int,
    user_id: int,
    max_characters: int = DEFAULT_MAX_CHARACTERS,
) -> DocumentPreview:
    """Extract an owned DOCX source file without changing persisted state."""

    try:
        document = get_owned_document(
            db,
            document_id=document_id,
            user_id=user_id,
        )
    except OwnedDocumentNotFoundError:
        raise DocumentPreviewNotFoundError("Document was not found.") from None
    except DocumentQueryError:
        raise DocumentPreviewUnavailableError(
            "Document metadata could not be read."
        ) from None

    if document.file_type != "DOCX":
        raise UnsupportedDocumentPreviewError(
            "Only DOCX documents support plain-text preview."
        )

    try:
        extracted = extract_document_text(
            storage,
            storage_key=document.storage_key,
            file_type=document.file_type,
            max_characters=max_characters,
        )
        content = extracted.text
        character_count = extracted.character_count
    except EmptyDocumentTextError:
        content = ""
        character_count = 0
    except DocumentExtractionLimitError:
        raise DocumentPreviewTooLargeError(
            "Document preview exceeds the processing limit."
        ) from None
    except DocumentExtractionError:
        raise DocumentPreviewUnavailableError(
            "Document preview could not be extracted."
        ) from None

    return DocumentPreview(
        document_id=document.id,
        title=document.title,
        original_filename=document.original_filename,
        file_type=document.file_type,
        content=content,
        character_count=character_count,
    )
