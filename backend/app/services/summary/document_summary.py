"""Owner-scoped hierarchical document summarization and persistence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from time import monotonic
from typing import Callable, cast

from sqlalchemy import case, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.document_summary import DocumentSummary
from app.services.document_deletion import document_not_being_deleted
from app.services.summary.concurrency import (
    SummaryConcurrencyCoordinator,
    SummaryConcurrencyLimits,
    get_summary_concurrency_coordinator,
)
from app.services.summary.gemini_summary import (
    GeneratedSummary,
    GeminiSummaryError,
    GeminiSummaryTimeoutError,
    SUMMARY_TYPES,
    SummaryProvider,
    SummaryStage,
    SummaryType,
)


DEFAULT_MAX_GROUP_CHARS = 12_000
DEFAULT_MAX_DOCUMENT_CHARS = 240_000
DEFAULT_MAX_PROVIDER_INPUT_CHARS = 480_000
DEFAULT_MAX_REQUESTS = 24
DEFAULT_MAX_REDUCTION_ROUNDS = 4
DEFAULT_SUMMARY_DEADLINE_SECONDS = 120.0


class DocumentSummaryError(Exception):
    """Base class for safe document summary service errors."""


class InvalidDocumentSummaryRequestError(DocumentSummaryError, ValueError):
    """Raised for invalid IDs, type, or limits."""


class SummaryDocumentNotFoundError(DocumentSummaryError):
    """Raised when an owned document does not exist."""


class SummaryDocumentNotReadyError(DocumentSummaryError):
    """Raised when document processing has not completed."""


class SummaryDocumentHasNoChunksError(DocumentSummaryError):
    """Raised when a READY document has no persisted chunks."""


class DocumentSummaryLimitError(DocumentSummaryError):
    """Raised before an unsafe amount of provider work is performed."""


class DocumentSummaryGenerationError(DocumentSummaryError):
    """Raised when an unknown provider failure occurs safely."""


class DocumentSummaryPersistenceError(DocumentSummaryError):
    """Raised when summary state cannot be read or written safely."""


class DocumentSummaryConflictError(DocumentSummaryPersistenceError):
    """Raised when source state changes or a race cannot be resolved."""


class DocumentSummaryDeadlineExceededError(DocumentSummaryError, TimeoutError):
    """Raised when the complete summary operation exceeds its deadline."""


@dataclass(frozen=True, slots=True)
class SummaryLimits:
    """Character-based safety limits; characters are not exact token counts."""

    max_group_chars: int = DEFAULT_MAX_GROUP_CHARS
    max_document_chars: int = DEFAULT_MAX_DOCUMENT_CHARS
    max_provider_input_chars: int = DEFAULT_MAX_PROVIDER_INPUT_CHARS
    max_requests: int = DEFAULT_MAX_REQUESTS
    max_reduction_rounds: int = DEFAULT_MAX_REDUCTION_ROUNDS

    def validate(self) -> None:
        values = (
            self.max_group_chars,
            self.max_document_chars,
            self.max_provider_input_chars,
            self.max_requests,
            self.max_reduction_rounds,
        )
        if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
            raise InvalidDocumentSummaryRequestError(
                "Summary limits must be integers."
            )
        if (
            self.max_group_chars < 64
            or self.max_document_chars < self.max_group_chars
            or self.max_provider_input_chars < self.max_group_chars
            or self.max_requests < 1
            or self.max_reduction_rounds < 1
        ):
            raise InvalidDocumentSummaryRequestError(
                "Summary limits are invalid."
            )


@dataclass(frozen=True, slots=True)
class DocumentSummaryResult:
    summary_id: int
    document_id: int
    summary_type: str
    content: str
    model_name: str
    created_at: datetime
    updated_at: datetime
    from_cache: bool


@dataclass(frozen=True, slots=True)
class StoredDocumentSummary:
    summary_id: int
    document_id: int
    summary_type: str
    content: str
    model_name: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class DocumentSummaryListResult:
    document_id: int
    items: tuple[StoredDocumentSummary, ...]


@dataclass(frozen=True, slots=True)
class _ChunkSnapshot:
    id: int
    chunk_index: int
    content: str


@dataclass(slots=True)
class _GenerationBudget:
    limits: SummaryLimits
    request_count: int = 0
    provider_input_chars: int = 0

    def reserve(self, input_chars: int) -> None:
        if self.request_count >= self.limits.max_requests:
            raise DocumentSummaryLimitError(
                "Document summary request limit was exceeded."
            )
        if self.provider_input_chars + input_chars > self.limits.max_provider_input_chars:
            raise DocumentSummaryLimitError(
                "Document summary input budget was exceeded."
            )
        self.request_count += 1
        self.provider_input_chars += input_chars


@dataclass(frozen=True, slots=True)
class _SummaryDeadline:
    expires_at: float
    clock: Callable[[], float]

    @classmethod
    def start(
        cls,
        seconds: float,
        clock: Callable[[], float],
    ) -> _SummaryDeadline:
        if (
            isinstance(seconds, bool)
            or not isinstance(seconds, (int, float))
            or not isfinite(seconds)
            or seconds <= 0
        ):
            raise InvalidDocumentSummaryRequestError(
                "Summary deadline must be positive and finite."
            )
        started_at = clock()
        if not isfinite(started_at):
            raise InvalidDocumentSummaryRequestError(
                "Summary deadline clock is invalid."
            )
        return cls(expires_at=started_at + seconds, clock=clock)

    def remaining_seconds(self) -> float:
        remaining = self.expires_at - self.clock()
        if (
            not isfinite(remaining)
            or remaining <= 0
            or int(remaining * 1_000) < 1
        ):
            raise DocumentSummaryDeadlineExceededError(
                "Document summary deadline was exceeded."
            )
        return remaining

    def expired(self) -> bool:
        remaining = self.expires_at - self.clock()
        return (
            not isfinite(remaining)
            or remaining <= 0
            or int(remaining * 1_000) < 1
        )


def summarize_document(
    db: Session,
    provider: SummaryProvider,
    *,
    document_id: int,
    user_id: int,
    summary_type: str,
    limits: SummaryLimits | None = None,
    concurrency_limits: SummaryConcurrencyLimits | None = None,
    concurrency_coordinator: SummaryConcurrencyCoordinator | None = None,
    deadline_seconds: float = DEFAULT_SUMMARY_DEADLINE_SECONDS,
    clock: Callable[[], float] = monotonic,
) -> DocumentSummaryResult:
    """Return a cached summary or generate and atomically persist a new one."""

    _validate_identifier(document_id, "document_id")
    _validate_identifier(user_id, "user_id")
    normalized_type = _normalize_summary_type(summary_type)
    active_limits = limits or SummaryLimits()
    active_limits.validate()
    deadline = _SummaryDeadline.start(deadline_seconds, clock)

    cached, chunks = _load_summary_source(
        db,
        document_id=document_id,
        user_id=user_id,
        summary_type=normalized_type,
    )
    if cached is not None:
        return cached

    coordinator = concurrency_coordinator or get_summary_concurrency_coordinator(
        db,
        concurrency_limits,
    )
    with coordinator.deduplicate(document_id, normalized_type) as lease:
        # A request may have observed a miss immediately before another process
        # committed the same summary and released its advisory lock.
        cached, chunks = _load_summary_source(
            db,
            document_id=document_id,
            user_id=user_id,
            summary_type=normalized_type,
        )
        if cached is not None:
            return cached

        total_chars = sum(len(chunk.content) for chunk in chunks)
        if total_chars > active_limits.max_document_chars:
            raise DocumentSummaryLimitError(
                "Document exceeds the safe summary size limit."
            )

        with lease.capacity(user_id):
            try:
                generated = _generate_hierarchical_summary(
                    provider,
                    chunks,
                    normalized_type,
                    active_limits,
                    deadline,
                )
            except (DocumentSummaryError, GeminiSummaryError):
                raise
            except Exception:
                raise DocumentSummaryGenerationError(
                    "Document summary generation failed."
                ) from None
            validated = _validate_generated_summary(generated)

            return _persist_summary(
                db,
                document_id=document_id,
                user_id=user_id,
                summary_type=normalized_type,
                generated=validated,
                source_chunks=chunks,
            )


def list_document_summaries(
    db: Session,
    *,
    document_id: int,
    user_id: int,
) -> DocumentSummaryListResult:
    """List at most one stored summary per supported type for an owner."""

    _validate_identifier(document_id, "document_id")
    _validate_identifier(user_id, "user_id")
    summary_order = case(
        (DocumentSummary.summary_type == "SHORT", 1),
        (DocumentSummary.summary_type == "STANDARD", 2),
        (DocumentSummary.summary_type == "DETAILED", 3),
        else_=4,
    )
    try:
        owned_document_id = db.scalar(
            select(Document.id).where(
                Document.id == document_id,
                Document.user_id == user_id,
                document_not_being_deleted(Document.id),
            )
        )
        if owned_document_id is None:
            raise SummaryDocumentNotFoundError("Document was not found.")
        summaries = db.scalars(
            select(DocumentSummary)
            .where(DocumentSummary.document_id == document_id)
            .order_by(summary_order.asc(), DocumentSummary.id.asc())
            .limit(3)
        ).all()
        result = DocumentSummaryListResult(
            document_id=document_id,
            items=tuple(_stored_summary(item) for item in summaries),
        )
    except DocumentSummaryError:
        _safe_rollback(db)
        raise
    except SQLAlchemyError:
        _safe_rollback(db)
        raise DocumentSummaryPersistenceError(
            "Document summaries could not be loaded."
        ) from None
    _end_read_transaction(db)
    return result


def _load_summary_source(
    db: Session,
    *,
    document_id: int,
    user_id: int,
    summary_type: SummaryType,
) -> tuple[DocumentSummaryResult | None, tuple[_ChunkSnapshot, ...]]:
    try:
        document = db.scalar(
            select(Document).where(
                Document.id == document_id,
                Document.user_id == user_id,
                document_not_being_deleted(Document.id),
            )
        )
        if document is None:
            raise SummaryDocumentNotFoundError("Document was not found.")
        if document.status != "READY":
            raise SummaryDocumentNotReadyError("Document is not ready.")
        rows = db.scalars(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.chunk_index.asc(), DocumentChunk.id.asc())
        ).all()
        if not rows:
            raise SummaryDocumentHasNoChunksError(
                "Document has no chunks to summarize."
            )
        chunks = tuple(
            _ChunkSnapshot(row.id, row.chunk_index, row.content)
            for row in rows
        )
        cached = db.scalar(
            select(DocumentSummary).where(
                DocumentSummary.document_id == document_id,
                DocumentSummary.summary_type == summary_type,
            )
        )
        result = (
            _result(cached, from_cache=True) if cached is not None else None,
            chunks,
        )
    except DocumentSummaryError:
        _safe_rollback(db)
        raise
    except SQLAlchemyError:
        _safe_rollback(db)
        raise DocumentSummaryPersistenceError(
            "Document summary state could not be loaded."
        ) from None
    _end_read_transaction(db)
    return result


def _generate_hierarchical_summary(
    provider: SummaryProvider,
    chunks: tuple[_ChunkSnapshot, ...],
    summary_type: SummaryType,
    limits: SummaryLimits,
    deadline: _SummaryDeadline,
) -> GeneratedSummary:
    blocks: list[str] = []
    for chunk in chunks:
        blocks.extend(
            _split_labeled_content(
                chunk.content,
                label=f"Đoạn {chunk.chunk_index + 1}",
                limit=limits.max_group_chars,
            )
        )
    groups = _pack_texts(blocks, limits.max_group_chars)
    budget = _GenerationBudget(limits)
    if len(groups) == 1:
        return _invoke_provider(
            provider, groups[0], summary_type, "FINAL", budget, deadline
        )

    current = [
        _invoke_provider(
            provider, group, summary_type, "MAP", budget, deadline
        ).content
        for group in groups
    ]
    for _round in range(limits.max_reduction_rounds + 1):
        combined_groups = _pack_texts(
            _split_unlabeled_texts(current, limits.max_group_chars),
            limits.max_group_chars,
        )
        if len(combined_groups) == 1:
            return _invoke_provider(
                provider,
                combined_groups[0],
                summary_type,
                "FINAL",
                budget,
                deadline,
            )
        if _round >= limits.max_reduction_rounds:
            raise DocumentSummaryLimitError(
                "Intermediate summaries could not be reduced safely."
            )
        previous_chars = sum(len(item) for item in current)
        reduced: list[str] = []
        for group in combined_groups:
            generated = _invoke_provider(
                provider, group, summary_type, "REDUCE", budget, deadline
            )
            reduced.append(generated.content)
        if sum(len(item) for item in reduced) >= previous_chars:
            raise DocumentSummaryLimitError(
                "Intermediate summary reduction did not reduce input size."
            )
        current = reduced
    raise DocumentSummaryLimitError(
        "Intermediate summaries exceeded the reduction limit."
    )


def _invoke_provider(
    provider: SummaryProvider,
    content: str,
    summary_type: SummaryType,
    stage: SummaryStage,
    budget: _GenerationBudget,
    deadline: _SummaryDeadline,
) -> GeneratedSummary:
    budget.reserve(len(content))
    remaining_seconds = deadline.remaining_seconds()
    try:
        generated = provider.generate_summary(
            content,
            summary_type,
            stage=stage,
            timeout_seconds=remaining_seconds,
        )
    except GeminiSummaryTimeoutError:
        if deadline.expired():
            raise DocumentSummaryDeadlineExceededError(
                "Document summary deadline was exceeded."
            ) from None
        raise
    deadline.remaining_seconds()
    return generated


def _split_labeled_content(content: str, *, label: str, limit: int) -> list[str]:
    prefix_reserve = len(label) + 24
    payload_limit = limit - prefix_reserve
    if payload_limit < 1:
        raise DocumentSummaryLimitError("Summary context limit is too small.")
    parts = [
        content[offset:offset + payload_limit]
        for offset in range(0, len(content), payload_limit)
    ]
    total = len(parts)
    return [
        f"[{label} — phần {index + 1}/{total}]\n{part}"
        for index, part in enumerate(parts)
    ]


def _split_unlabeled_texts(texts: list[str], limit: int) -> list[str]:
    parts: list[str] = []
    for text in texts:
        parts.extend(
            text[offset:offset + limit]
            for offset in range(0, len(text), limit)
        )
    return parts


def _pack_texts(texts: list[str], limit: int) -> list[str]:
    groups: list[str] = []
    current: list[str] = []
    current_chars = 0
    for text in texts:
        separator_chars = 2 if current else 0
        if current and current_chars + separator_chars + len(text) > limit:
            groups.append("\n\n".join(current))
            current = []
            current_chars = 0
            separator_chars = 0
        if len(text) > limit:
            raise DocumentSummaryLimitError(
                "Summary group exceeded its context limit."
            )
        current.append(text)
        current_chars += separator_chars + len(text)
    if current:
        groups.append("\n\n".join(current))
    if not groups:
        raise DocumentSummaryLimitError("Summary input was empty.")
    return groups


def _persist_summary(
    db: Session,
    *,
    document_id: int,
    user_id: int,
    summary_type: SummaryType,
    generated: GeneratedSummary,
    source_chunks: tuple[_ChunkSnapshot, ...],
) -> DocumentSummaryResult:
    try:
        document = db.scalar(
            select(Document)
            .where(
                Document.id == document_id,
                Document.user_id == user_id,
                document_not_being_deleted(Document.id),
            )
            .with_for_update()
        )
        if document is None:
            raise SummaryDocumentNotFoundError("Document was not found.")
        if document.status != "READY":
            raise SummaryDocumentNotReadyError("Document is not ready.")

        cached = db.scalar(
            select(DocumentSummary).where(
                DocumentSummary.document_id == document_id,
                DocumentSummary.summary_type == summary_type,
            )
        )
        if cached is not None:
            result = _result(cached, from_cache=True)
            db.rollback()
            return result

        current_chunks = db.scalars(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.chunk_index.asc(), DocumentChunk.id.asc())
        ).all()
        current_snapshot = tuple(
            _ChunkSnapshot(row.id, row.chunk_index, row.content)
            for row in current_chunks
        )
        if current_snapshot != source_chunks:
            raise DocumentSummaryConflictError(
                "Document chunks changed during summary generation."
            )

        summary = DocumentSummary(
            document_id=document_id,
            summary_type=summary_type,
            content=generated.content,
            model_name=generated.model_name,
        )
        db.add(summary)
        db.flush()
        db.refresh(summary)
        result = _result(summary, from_cache=False)
        db.commit()
        return result
    except IntegrityError:
        _safe_rollback(db)
        cached_result = _load_cached_after_conflict(
            db,
            document_id=document_id,
            user_id=user_id,
            summary_type=summary_type,
        )
        if cached_result is not None:
            return cached_result
        raise DocumentSummaryConflictError(
            "A concurrent summary request could not be resolved."
        ) from None
    except DocumentSummaryError:
        _safe_rollback(db)
        raise
    except SQLAlchemyError:
        _safe_rollback(db)
        raise DocumentSummaryPersistenceError(
            "Document summary could not be saved."
        ) from None


def _load_cached_after_conflict(
    db: Session,
    *,
    document_id: int,
    user_id: int,
    summary_type: SummaryType,
) -> DocumentSummaryResult | None:
    try:
        cached = db.scalar(
            select(DocumentSummary)
            .join(Document, Document.id == DocumentSummary.document_id)
            .where(
                DocumentSummary.document_id == document_id,
                DocumentSummary.summary_type == summary_type,
                Document.user_id == user_id,
                document_not_being_deleted(Document.id),
            )
        )
        if cached is not None:
            result = _result(cached, from_cache=True)
        else:
            result = None
        db.rollback()
        return result
    except SQLAlchemyError:
        _safe_rollback(db)
        return None


def _validate_generated_summary(generated: object) -> GeneratedSummary:
    if (
        not isinstance(generated, GeneratedSummary)
        or not generated.content.strip()
        or not generated.model_name.strip()
        or len(generated.model_name.strip()) > 100
    ):
        raise DocumentSummaryGenerationError(
            "Summary provider returned an invalid result."
        )
    return GeneratedSummary(
        content=generated.content.strip(),
        model_name=generated.model_name.strip(),
    )


def _result(summary: DocumentSummary, *, from_cache: bool) -> DocumentSummaryResult:
    return DocumentSummaryResult(
        summary_id=summary.id,
        document_id=summary.document_id,
        summary_type=summary.summary_type,
        content=summary.content,
        model_name=summary.model_name,
        created_at=summary.created_at,
        updated_at=summary.updated_at,
        from_cache=from_cache,
    )


def _stored_summary(summary: DocumentSummary) -> StoredDocumentSummary:
    return StoredDocumentSummary(
        summary_id=summary.id,
        document_id=summary.document_id,
        summary_type=summary.summary_type,
        content=summary.content,
        model_name=summary.model_name,
        created_at=summary.created_at,
        updated_at=summary.updated_at,
    )


def _normalize_summary_type(summary_type: str) -> SummaryType:
    if not isinstance(summary_type, str):
        raise InvalidDocumentSummaryRequestError(
            "summary_type must be a string."
        )
    normalized = summary_type.strip().upper()
    if normalized not in SUMMARY_TYPES:
        raise InvalidDocumentSummaryRequestError("summary_type is invalid.")
    return cast(SummaryType, normalized)


def _validate_identifier(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise InvalidDocumentSummaryRequestError(
            f"{name} must be a positive integer."
        )


def _end_read_transaction(db: Session) -> None:
    try:
        db.rollback()
    except SQLAlchemyError:
        raise DocumentSummaryPersistenceError(
            "Document summary read transaction could not be released."
        ) from None


def _safe_rollback(db: Session) -> None:
    try:
        db.rollback()
    except SQLAlchemyError:
        pass
