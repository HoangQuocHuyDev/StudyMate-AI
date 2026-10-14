"""Offset-safe text chunking for the StudyMate AI retrieval pipeline."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.document_extractor import ExtractedText


DEFAULT_CHUNK_SIZE = 800
DEFAULT_CHUNK_OVERLAP = 150
MAX_TEXT_CHARACTERS = 2_000_000
MAX_CHUNK_SIZE = MAX_TEXT_CHARACTERS
MAX_CHUNKS = 10_000

_PARAGRAPH_BOUNDARY = re.compile(r"(?:\r?\n)[ \t]*(?:\r?\n)")
_NEWLINE_BOUNDARY = re.compile(r"\n")
_SENTENCE_BOUNDARY = re.compile(r"[.!?\u3002\uff01\uff1f](?=\s|$)")
_WHITESPACE_BOUNDARY = re.compile(r"\s+")


class TextChunkingError(Exception):
    """Base error for controlled text chunking failures."""


class InvalidTextError(TextChunkingError, TypeError):
    """Raised when the text or extracted-text input is invalid."""


class InvalidChunkConfigurationError(TextChunkingError, ValueError):
    """Raised when chunk size or overlap is invalid."""


class ChunkingLimitError(TextChunkingError):
    """Raised when chunking would exceed a bounded resource limit."""


@dataclass(frozen=True, slots=True)
class TextChunk:
    """One exact slice of source text and its retrieval metadata."""

    index: int
    text: str
    start_char: int
    end_char: int
    character_count: int
    page_number: int | None


def chunk_text(
    text: str,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[TextChunk]:
    """Split text into bounded, overlapping, offset-safe chunks."""

    _validate_inputs(text, chunk_size, chunk_overlap)
    if not text or text.isspace():
        return []

    return _chunk_region(
        text,
        region_start=0,
        region_end=len(text),
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        page_number=None,
        index_offset=0,
    )


def chunk_extracted_text(
    extracted: ExtractedText,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[TextChunk]:
    """Chunk an extractor result, retaining reliable PDF page metadata."""

    if not isinstance(extracted, ExtractedText):
        raise InvalidTextError("extracted must be an ExtractedText instance.")
    _validate_inputs(extracted.text, chunk_size, chunk_overlap)
    if not extracted.text or extracted.text.isspace():
        return []

    if extracted.file_type.upper() != "PDF":
        return chunk_text(
            extracted.text,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

    page_spans = _reliable_pdf_page_spans(extracted)
    if page_spans is None:
        return chunk_text(
            extracted.text,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

    chunks: list[TextChunk] = []
    for page_number, page_start, page_end in page_spans:
        page_chunks = _chunk_region(
            extracted.text,
            region_start=page_start,
            region_end=page_end,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            page_number=page_number,
            index_offset=len(chunks),
        )
        if len(chunks) + len(page_chunks) > MAX_CHUNKS:
            raise ChunkingLimitError(
                "Chunk count exceeds the configured processing limit."
            )
        chunks.extend(page_chunks)
    return chunks


def _validate_inputs(text: str, chunk_size: int, chunk_overlap: int) -> None:
    if not isinstance(text, str):
        raise InvalidTextError("text must be a string.")
    if isinstance(chunk_size, bool) or not isinstance(chunk_size, int):
        raise InvalidChunkConfigurationError(
            "chunk_size must be a positive integer."
        )
    if chunk_size <= 0:
        raise InvalidChunkConfigurationError(
            "chunk_size must be a positive integer."
        )
    if chunk_size > MAX_CHUNK_SIZE:
        raise InvalidChunkConfigurationError(
            "chunk_size exceeds the configured processing limit."
        )
    if isinstance(chunk_overlap, bool) or not isinstance(chunk_overlap, int):
        raise InvalidChunkConfigurationError(
            "chunk_overlap must be a non-negative integer."
        )
    if chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise InvalidChunkConfigurationError(
            "chunk_overlap must be non-negative and smaller than chunk_size."
        )
    if len(text) > MAX_TEXT_CHARACTERS:
        raise ChunkingLimitError(
            "Text exceeds the configured character limit."
        )


def _chunk_region(
    source: str,
    *,
    region_start: int,
    region_end: int,
    chunk_size: int,
    chunk_overlap: int,
    page_number: int | None,
    index_offset: int,
) -> list[TextChunk]:
    if region_start >= region_end or source[region_start:region_end].isspace():
        return []

    chunks: list[TextChunk] = []
    start = region_start
    covered_until = region_start

    while start < region_end and covered_until < region_end:
        if len(chunks) + index_offset >= MAX_CHUNKS:
            raise ChunkingLimitError(
                "Chunk count exceeds the configured processing limit."
            )

        hard_end = min(start + chunk_size, region_end)
        end = _choose_chunk_end(
            source,
            start=start,
            hard_end=hard_end,
            region_end=region_end,
            minimum_end=covered_until + 1,
        )
        chunk_value = source[start:end]
        chunks.append(
            TextChunk(
                index=index_offset + len(chunks),
                text=chunk_value,
                start_char=start,
                end_char=end,
                character_count=len(chunk_value),
                page_number=page_number,
            )
        )
        covered_until = max(covered_until, end)
        if covered_until >= region_end:
            break

        start = _choose_next_start(
            source,
            current_start=start,
            current_end=end,
            chunk_overlap=chunk_overlap,
        )

    return chunks


def _choose_chunk_end(
    source: str,
    *,
    start: int,
    hard_end: int,
    region_end: int,
    minimum_end: int,
) -> int:
    if hard_end >= region_end:
        return region_end

    preferred_start = max(start + 1, minimum_end)
    if preferred_start > hard_end:
        return hard_end

    boundary_patterns = (
        _PARAGRAPH_BOUNDARY,
        _NEWLINE_BOUNDARY,
        _SENTENCE_BOUNDARY,
        _WHITESPACE_BOUNDARY,
    )
    for pattern in boundary_patterns:
        candidate = _last_boundary(
            pattern,
            source,
            search_start=start,
            search_end=hard_end,
            minimum=preferred_start,
        )
        if candidate is not None:
            return candidate
    return hard_end


def _last_boundary(
    pattern: re.Pattern[str],
    source: str,
    *,
    search_start: int,
    search_end: int,
    minimum: int,
) -> int | None:
    candidate: int | None = None
    for match in pattern.finditer(source, search_start, search_end):
        boundary = match.end()
        if minimum <= boundary <= search_end:
            candidate = boundary
    return candidate


def _choose_next_start(
    source: str,
    *,
    current_start: int,
    current_end: int,
    chunk_overlap: int,
) -> int:
    if chunk_overlap == 0:
        return current_end

    target = max(current_start + 1, current_end - chunk_overlap)
    if target >= current_end:
        return current_start + 1

    candidates: list[int] = []
    for pattern in (
        _PARAGRAPH_BOUNDARY,
        _NEWLINE_BOUNDARY,
        _SENTENCE_BOUNDARY,
        _WHITESPACE_BOUNDARY,
    ):
        match = pattern.search(source, target, current_end)
        if match is not None and match.end() < current_end:
            candidates.append(match.end())

    if candidates:
        return min(candidates)
    return target


def _reliable_pdf_page_spans(
    extracted: ExtractedText,
) -> list[tuple[int, int, int]] | None:
    page_count = extracted.page_count
    if (
        isinstance(page_count, bool)
        or not isinstance(page_count, int)
        or page_count <= 0
    ):
        return None

    separators = [
        index for index, character in enumerate(extracted.text) if character == "\f"
    ]
    if len(separators) != page_count - 1:
        return None

    spans: list[tuple[int, int, int]] = []
    start = 0
    for page_number, separator in enumerate(separators, start=1):
        spans.append((page_number, start, separator))
        start = separator + 1
    spans.append((page_count, start, len(extracted.text)))
    return spans
