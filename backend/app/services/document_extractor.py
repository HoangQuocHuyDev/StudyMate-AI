"""Bounded text extraction for documents already stored by StudyMate AI."""

from __future__ import annotations

import os
import re
import stat
import unicodedata
from dataclasses import dataclass
from typing import BinaryIO, Iterator
from zipfile import BadZipFile, ZipFile

from docx import Document as DocxDocument
from docx.opc.exceptions import PackageNotFoundError
from docx.table import Table
from docx.text.paragraph import Paragraph
from lxml.etree import XMLSyntaxError
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.services.file_storage import FileStorage, FileStorageError


DEFAULT_MAX_CHARACTERS = 2_000_000
DEFAULT_MAX_PDF_PAGES = 500
DEFAULT_MAX_DOCX_BLOCKS = 10_000
MAX_DOCX_ENTRIES = 1_000
MAX_DOCX_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
MAX_DOCX_COMPRESSION_RATIO = 100
SUPPORTED_FILE_TYPES = frozenset({"PDF", "DOCX"})


class DocumentExtractionError(Exception):
    """Base error for controlled document extraction failures."""


class UnsupportedDocumentTypeError(DocumentExtractionError):
    """Raised when no extractor exists for a document type."""


class DocumentAccessError(DocumentExtractionError):
    """Raised when stored bytes cannot be opened safely."""


class EmptyDocumentTextError(DocumentExtractionError):
    """Raised when a document has no usable extractable text."""


class DocumentExtractionLimitError(DocumentExtractionError):
    """Raised when extraction would exceed a configured resource limit."""


class EncryptedDocumentError(DocumentExtractionError):
    """Raised when an encrypted PDF cannot be processed safely."""


@dataclass(frozen=True, slots=True)
class ExtractedText:
    """Normalized text and metadata for downstream chunking."""

    text: str
    file_type: str
    character_count: int
    page_count: int | None


class _TextCollector:
    def __init__(self, max_characters: int) -> None:
        self._max_characters = max_characters
        self._parts: list[str] = []
        self._character_count = 0

    def add(
        self,
        value: str | None,
        *,
        separator: str = "\n\n",
        include_empty: bool = False,
    ) -> None:
        if not value and not include_empty:
            return
        value = value or ""
        separator_length = len(separator) if self._parts else 0
        projected_count = self._character_count + separator_length + len(value)
        if projected_count > self._max_characters:
            raise DocumentExtractionLimitError(
                "Extracted text exceeds the configured character limit."
            )
        if self._parts:
            self._parts.append(separator)
        self._parts.append(value)
        self._character_count = projected_count

    def build(self) -> str:
        return "".join(self._parts)


class _StructureBudget:
    def __init__(self, maximum: int) -> None:
        self._maximum = maximum
        self._count = 0

    def consume(self) -> None:
        self._count += 1
        if self._count > self._maximum:
            raise DocumentExtractionLimitError(
                "DOCX structure exceeds the configured processing limit."
            )


def extract_document_text(
    storage: FileStorage,
    *,
    storage_key: str,
    file_type: str,
    max_file_size: int | None = None,
    max_characters: int = DEFAULT_MAX_CHARACTERS,
    max_pdf_pages: int = DEFAULT_MAX_PDF_PAGES,
    max_docx_blocks: int = DEFAULT_MAX_DOCX_BLOCKS,
) -> ExtractedText:
    """Extract normalized text from one safely stored PDF or DOCX file."""

    normalized_file_type = _normalize_file_type(file_type)
    _validate_positive_limit(max_characters, "max_characters")
    _validate_positive_limit(max_pdf_pages, "max_pdf_pages")
    _validate_positive_limit(max_docx_blocks, "max_docx_blocks")
    if max_file_size is not None:
        _validate_positive_limit(max_file_size, "max_file_size")
    effective_file_limit = min(
        storage.max_file_size,
        max_file_size if max_file_size is not None else storage.max_file_size,
    )

    try:
        with storage.open_binary(storage_key) as stream:
            file_size = _get_stream_size(stream)
            if file_size == 0:
                raise EmptyDocumentTextError(
                    "Document does not contain extractable text."
                )
            if file_size > effective_file_limit:
                raise DocumentExtractionLimitError(
                    "Document exceeds the configured extraction size limit."
                )

            if normalized_file_type == "DOCX":
                raw_text = _extract_docx(
                    stream,
                    max_characters=max_characters,
                    max_blocks=max_docx_blocks,
                )
                page_count = None
            else:
                raw_text, page_count = _extract_pdf(
                    stream,
                    max_characters=max_characters,
                    max_pages=max_pdf_pages,
                )
    except FileStorageError as exc:
        raise DocumentAccessError(
            "Stored document cannot be accessed safely."
        ) from exc

    text = normalize_extracted_text(raw_text)
    if not text:
        if normalized_file_type == "PDF":
            raise EmptyDocumentTextError(
                "PDF has no extractable text layer; OCR is not supported."
            )
        raise EmptyDocumentTextError(
            "Document does not contain extractable text."
        )
    if len(text) > max_characters:
        raise DocumentExtractionLimitError(
            "Extracted text exceeds the configured character limit."
        )

    return ExtractedText(
        text=text,
        file_type=normalized_file_type,
        character_count=len(text),
        page_count=page_count,
    )


def normalize_extracted_text(value: str) -> str:
    """Normalize layout noise while retaining paragraphs and page boundaries."""

    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    normalized = "".join(
        character
        for character in normalized
        if character in {"\n", "\t", "\f"}
        or unicodedata.category(character) != "Cc"
    )
    normalized = normalized.replace("\f", "\n\f\n")
    lines = [
        "\f" if line == "\f" else re.sub(r"[\t\v ]+", " ", line).strip()
        for line in normalized.split("\n")
    ]
    normalized = "\n".join(lines)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    normalized = re.sub(r"\n*\f\n*", "\n\n\f\n\n", normalized)
    return normalized.strip()


def _normalize_file_type(file_type: str) -> str:
    if not isinstance(file_type, str):
        raise UnsupportedDocumentTypeError("Document type is not supported.")
    normalized = file_type.upper()
    if normalized not in SUPPORTED_FILE_TYPES:
        raise UnsupportedDocumentTypeError("Document type is not supported.")
    return normalized


def _validate_positive_limit(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer.")


def _get_stream_size(stream: BinaryIO) -> int:
    try:
        file_status = os.fstat(stream.fileno())
        if not stat.S_ISREG(file_status.st_mode) or file_status.st_size < 0:
            raise OSError("Stored source is not a regular file.")
        stream.seek(0)
        return file_status.st_size
    except (OSError, TypeError, ValueError) as exc:
        raise DocumentAccessError(
            "Stored document cannot be inspected safely."
        ) from exc


def _extract_docx(
    stream: BinaryIO,
    *,
    max_characters: int,
    max_blocks: int,
) -> str:
    _validate_docx_archive(stream)
    try:
        stream.seek(0)
        document = DocxDocument(stream)
        budget = _StructureBudget(max_blocks)
        collector = _TextCollector(max_characters)
        for fragment in _iter_docx_fragments(document, budget):
            collector.add(fragment)
        return collector.build()
    except DocumentExtractionError:
        raise
    except (
        BadZipFile,
        KeyError,
        OSError,
        PackageNotFoundError,
        ValueError,
        XMLSyntaxError,
    ) as exc:
        raise DocumentExtractionError(
            "DOCX document is damaged or invalid."
        ) from exc


def _iter_docx_fragments(container: object, budget: _StructureBudget) -> Iterator[str]:
    for block in container.iter_inner_content():  # type: ignore[attr-defined]
        budget.consume()
        if isinstance(block, Paragraph):
            if block.text:
                yield block.text
            continue
        if not isinstance(block, Table):
            continue

        for row in block.rows:
            budget.consume()
            cell_values: list[str] = []
            for cell in row.cells:
                budget.consume()
                cell_text = "\n".join(_iter_docx_fragments(cell, budget)).strip()
                cell_values.append(cell_text)
            row_text = " | ".join(cell_values).strip()
            if row_text:
                yield row_text


def _validate_docx_archive(stream: BinaryIO) -> None:
    try:
        stream.seek(0)
        with ZipFile(stream) as archive:
            entries = archive.infolist()
            if not entries or len(entries) > MAX_DOCX_ENTRIES:
                raise DocumentExtractionLimitError(
                    "DOCX archive exceeds the configured entry limit."
                )

            total_uncompressed = 0
            total_compressed = 0
            for entry in entries:
                if entry.flag_bits & 0x1:
                    raise DocumentExtractionError(
                        "Encrypted DOCX archives are not supported."
                    )
                total_uncompressed += entry.file_size
                total_compressed += entry.compress_size
                if entry.file_size and (
                    entry.compress_size == 0
                    or entry.file_size / entry.compress_size
                    > MAX_DOCX_COMPRESSION_RATIO
                ):
                    raise DocumentExtractionLimitError(
                        "DOCX archive compression ratio is unsafe."
                    )

            if total_uncompressed > MAX_DOCX_UNCOMPRESSED_BYTES:
                raise DocumentExtractionLimitError(
                    "DOCX archive exceeds the uncompressed size limit."
                )
            if total_uncompressed and (
                total_compressed == 0
                or total_uncompressed / total_compressed
                > MAX_DOCX_COMPRESSION_RATIO
            ):
                raise DocumentExtractionLimitError(
                    "DOCX archive compression ratio is unsafe."
                )
    except DocumentExtractionError:
        raise
    except (BadZipFile, OSError, ValueError) as exc:
        raise DocumentExtractionError(
            "DOCX document is damaged or invalid."
        ) from exc
    finally:
        try:
            stream.seek(0)
        except (OSError, ValueError):
            pass


def _extract_pdf(
    stream: BinaryIO,
    *,
    max_characters: int,
    max_pages: int,
) -> tuple[str, int]:
    try:
        stream.seek(0)
        reader = PdfReader(stream, strict=False)
        if reader.is_encrypted:
            raise EncryptedDocumentError(
                "Encrypted PDF documents are not supported."
            )

        page_count = len(reader.pages)
        if page_count > max_pages:
            raise DocumentExtractionLimitError(
                "PDF exceeds the configured page limit."
            )

        collector = _TextCollector(max_characters)
        for page in reader.pages:
            collector.add(
                page.extract_text(),
                separator="\n\n\f\n\n",
                include_empty=True,
            )
        return collector.build(), page_count
    except DocumentExtractionError:
        raise
    except (OSError, PdfReadError, TypeError, ValueError) as exc:
        raise DocumentExtractionError(
            "PDF document is damaged or unreadable."
        ) from exc
