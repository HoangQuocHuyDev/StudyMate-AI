"""Durable, leased orchestration for deleting one owned document safely."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.models.document import Document
from app.models.document_deletion_job import DocumentDeletionJob
from app.services.file_storage import FileStorage, FileStorageError


PENDING = "PENDING"
RUNNING = "RUNNING"
FAILED = "FAILED"
COMPLETED = "COMPLETED"
VECTOR_CLEANUP = "VECTOR_CLEANUP"
FILE_CLEANUP = "FILE_CLEANUP"
DATABASE_DELETE = "DATABASE_DELETE"
DONE = "DONE"
DEFAULT_LEASE_SECONDS = 60
DEFAULT_RECOVERY_LIMIT = 100


class DeletionVectorStore(Protocol):
    """Owner-scoped ChromaDB operations used by deletion."""

    def delete_document_vectors(self, *, user_id: int, document_id: int) -> None:
        """Idempotently delete one document's vectors."""

    def get_document_vector_ids(
        self,
        *,
        user_id: int,
        document_id: int,
    ) -> set[str]:
        """Return remaining vector IDs for deletion verification."""


class DocumentDeletionError(Exception):
    """Base error for safe document deletion failures."""


class DocumentDeletionNotFoundError(DocumentDeletionError):
    """Raised when the document/job is absent or owned by someone else."""


class DocumentDeletionConflictError(DocumentDeletionError):
    """Raised when state or a live lease prevents deletion."""


class DocumentDeletionExternalError(DocumentDeletionError):
    """Raised after a ChromaDB or file-storage failure is recorded."""


class DocumentDeletionInfrastructureError(DocumentDeletionError):
    """Raised when durable PostgreSQL state cannot be confirmed."""


@dataclass(frozen=True, slots=True)
class DocumentDeletionResult:
    """Internal result confirming the workflow reached COMPLETED."""

    document_id: int
    status: str


@dataclass(frozen=True, slots=True)
class DocumentDeletionRecoveryResult:
    """Aggregate result from one explicit recovery sweep."""

    discovered: int
    completed: int
    failed: int
    conflicted: int


@dataclass(frozen=True, slots=True)
class _ClaimedJobSnapshot:
    current_step: str
    storage_key: str | None


def document_not_being_deleted(
    document_id: ColumnElement[int],
) -> ColumnElement[bool]:
    """Return a reusable SQL tombstone predicate for document operations."""

    active_job = (
        select(DocumentDeletionJob.id)
        .where(
            DocumentDeletionJob.document_id == document_id,
            DocumentDeletionJob.status != COMPLETED,
        )
        .correlate_except(DocumentDeletionJob)
        .exists()
    )
    return ~active_job


def delete_owned_document(
    db: Session,
    vector_store: DeletionVectorStore,
    storage: FileStorage,
    *,
    document_id: int,
    user_id: int,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> DocumentDeletionResult:
    """Create/resume a deletion job and synchronously run it to completion."""

    _validate_identifier(document_id)
    _validate_identifier(user_id)
    _validate_lease_seconds(lease_seconds)
    completed = _prepare_job(db, document_id=document_id, user_id=user_id)
    if completed:
        return DocumentDeletionResult(document_id=document_id, status=COMPLETED)

    lease_token = _claim_job(
        db,
        document_id=document_id,
        user_id=user_id,
        lease_seconds=lease_seconds,
    )
    return _run_claimed_job(
        db,
        vector_store,
        storage,
        document_id=document_id,
        user_id=user_id,
        lease_token=lease_token,
    )


def recover_document_deletions(
    session_factory: Callable[[], Session],
    vector_store: DeletionVectorStore,
    storage: FileStorage,
    *,
    limit: int = DEFAULT_RECOVERY_LIMIT,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> DocumentDeletionRecoveryResult:
    """Explicitly resume claimable jobs; never scheduled at application startup."""

    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
        raise ValueError("limit must be between 1 and 500.")
    _validate_lease_seconds(lease_seconds)
    with session_factory() as discovery_session:
        try:
            job_keys = list(
                discovery_session.execute(
                    select(
                        DocumentDeletionJob.document_id,
                        DocumentDeletionJob.user_id,
                    )
                    .where(_claimable_job_predicate())
                    .order_by(
                        DocumentDeletionJob.updated_at,
                        DocumentDeletionJob.id,
                    )
                    .limit(limit)
                ).all()
            )
            discovery_session.rollback()
        except SQLAlchemyError:
            _safe_rollback(discovery_session)
            raise DocumentDeletionInfrastructureError(
                "Deletion recovery jobs could not be discovered."
            ) from None

    completed = 0
    failed = 0
    conflicted = 0
    for document_id, user_id in job_keys:
        with session_factory() as job_session:
            try:
                delete_owned_document(
                    job_session,
                    vector_store,
                    storage,
                    document_id=document_id,
                    user_id=user_id,
                    lease_seconds=lease_seconds,
                )
            except DocumentDeletionConflictError:
                conflicted += 1
            except DocumentDeletionError:
                failed += 1
            else:
                completed += 1
    return DocumentDeletionRecoveryResult(
        discovered=len(job_keys),
        completed=completed,
        failed=failed,
        conflicted=conflicted,
    )


def _prepare_job(db: Session, *, document_id: int, user_id: int) -> bool:
    """Lock the document, validate state, and durably create its tombstone."""

    try:
        document = db.scalar(
            select(Document)
            .where(Document.id == document_id, Document.user_id == user_id)
            .with_for_update()
        )
        if document is None:
            existing_job = db.scalar(
                select(DocumentDeletionJob)
                .where(
                    DocumentDeletionJob.document_id == document_id,
                    DocumentDeletionJob.user_id == user_id,
                )
                .with_for_update()
            )
            if existing_job is None:
                db.rollback()
                raise DocumentDeletionNotFoundError("Document was not found.")
            if existing_job.status == COMPLETED:
                db.rollback()
                return True
        else:
            if document.status == "PROCESSING" or document.rag_status == "INDEXING":
                db.rollback()
                raise DocumentDeletionConflictError(
                    "Document is currently being processed."
                )
            existing_job = db.scalar(
                select(DocumentDeletionJob)
                .where(DocumentDeletionJob.document_id == document_id)
                .with_for_update()
            )
            if existing_job is None:
                db.add(
                    DocumentDeletionJob(
                        document_id=document_id,
                        user_id=user_id,
                        storage_key=document.storage_key,
                    )
                )
                db.commit()
                return False
            if existing_job.user_id != user_id:
                db.rollback()
                raise DocumentDeletionNotFoundError("Document was not found.")

        if existing_job.status == COMPLETED:
            db.rollback()
            return True
        db.commit()
        return False
    except (DocumentDeletionNotFoundError, DocumentDeletionConflictError):
        raise
    except IntegrityError:
        _safe_rollback(db)
        # A concurrent creator won the unique document_id constraint. The
        # normal claim step will safely resolve the job or live lease.
        return False
    except SQLAlchemyError:
        _safe_rollback(db)
        raise DocumentDeletionInfrastructureError(
            "Document deletion could not be prepared."
        ) from None


def _claim_job(
    db: Session,
    *,
    document_id: int,
    user_id: int,
    lease_seconds: int,
) -> UUID:
    lease_token = uuid4()
    lease_expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=lease_seconds
    )
    statement = (
        update(DocumentDeletionJob)
        .where(
            DocumentDeletionJob.document_id == document_id,
            DocumentDeletionJob.user_id == user_id,
            _claimable_job_predicate(),
        )
        .values(
            status=RUNNING,
            attempt_count=DocumentDeletionJob.attempt_count + 1,
            lease_token=lease_token,
            lease_expires_at=lease_expires_at,
            last_error_code=None,
            last_error_at=None,
            updated_at=func.current_timestamp(),
        )
        .returning(DocumentDeletionJob.id)
        .execution_options(synchronize_session=False)
    )
    try:
        job_id = db.scalar(statement)
        if job_id is None:
            job = db.scalar(
                select(DocumentDeletionJob).where(
                    DocumentDeletionJob.document_id == document_id,
                    DocumentDeletionJob.user_id == user_id,
                )
            )
            job_status = job.status if job is not None else None
            db.rollback()
            if job is None:
                raise DocumentDeletionNotFoundError("Document was not found.")
            if job_status == COMPLETED:
                raise DocumentDeletionConflictError(
                    "Document deletion has already completed."
                )
            raise DocumentDeletionConflictError(
                "Document deletion is already in progress."
            )
        db.commit()
        return lease_token
    except (DocumentDeletionNotFoundError, DocumentDeletionConflictError):
        raise
    except SQLAlchemyError:
        _safe_rollback(db)
        raise DocumentDeletionInfrastructureError(
            "Document deletion job could not be claimed."
        ) from None


def _run_claimed_job(
    db: Session,
    vector_store: DeletionVectorStore,
    storage: FileStorage,
    *,
    document_id: int,
    user_id: int,
    lease_token: UUID,
) -> DocumentDeletionResult:
    while True:
        job = _load_owned_lease(
            db,
            document_id=document_id,
            user_id=user_id,
            lease_token=lease_token,
        )
        if job.current_step == VECTOR_CLEANUP:
            try:
                vector_store.delete_document_vectors(
                    user_id=user_id,
                    document_id=document_id,
                )
                remaining = vector_store.get_document_vector_ids(
                    user_id=user_id,
                    document_id=document_id,
                )
                if remaining:
                    raise RuntimeError("Vector verification failed.")
            except Exception:
                _mark_failed(
                    db,
                    document_id=document_id,
                    user_id=user_id,
                    lease_token=lease_token,
                    error_code="vector_cleanup_failed",
                )
                raise DocumentDeletionExternalError(
                    "Document vectors could not be deleted."
                ) from None
            _advance_step(
                db,
                document_id=document_id,
                user_id=user_id,
                lease_token=lease_token,
                expected_step=VECTOR_CLEANUP,
                next_step=FILE_CLEANUP,
            )
            continue

        if job.current_step == FILE_CLEANUP:
            if job.storage_key is None:
                _mark_failed(
                    db,
                    document_id=document_id,
                    user_id=user_id,
                    lease_token=lease_token,
                    error_code="file_cleanup_state_invalid",
                )
                raise DocumentDeletionInfrastructureError(
                    "Document deletion state is invalid."
                )
            try:
                storage.delete(job.storage_key)
            except FileStorageError:
                _mark_failed(
                    db,
                    document_id=document_id,
                    user_id=user_id,
                    lease_token=lease_token,
                    error_code="file_cleanup_failed",
                )
                raise DocumentDeletionExternalError(
                    "Document file could not be deleted."
                ) from None
            _advance_step(
                db,
                document_id=document_id,
                user_id=user_id,
                lease_token=lease_token,
                expected_step=FILE_CLEANUP,
                next_step=DATABASE_DELETE,
                clear_storage_key=True,
            )
            continue

        if job.current_step == DATABASE_DELETE:
            _delete_database_records(
                db,
                document_id=document_id,
                user_id=user_id,
                lease_token=lease_token,
            )
            return DocumentDeletionResult(
                document_id=document_id,
                status=COMPLETED,
            )

        raise DocumentDeletionInfrastructureError(
            "Document deletion state is invalid."
        )


def _load_owned_lease(
    db: Session,
    *,
    document_id: int,
    user_id: int,
    lease_token: UUID,
) -> _ClaimedJobSnapshot:
    try:
        job = db.scalar(
            select(DocumentDeletionJob).where(
                DocumentDeletionJob.document_id == document_id,
                DocumentDeletionJob.user_id == user_id,
                DocumentDeletionJob.status == RUNNING,
                DocumentDeletionJob.lease_token == lease_token,
            )
        )
        snapshot = (
            _ClaimedJobSnapshot(
                current_step=job.current_step,
                storage_key=job.storage_key,
            )
            if job is not None
            else None
        )
        db.rollback()
    except SQLAlchemyError:
        _safe_rollback(db)
        raise DocumentDeletionInfrastructureError(
            "Document deletion state could not be loaded."
        ) from None
    if snapshot is None:
        raise DocumentDeletionConflictError(
            "Document deletion lease is no longer owned by this worker."
        )
    return snapshot


def _advance_step(
    db: Session,
    *,
    document_id: int,
    user_id: int,
    lease_token: UUID,
    expected_step: str,
    next_step: str,
    clear_storage_key: bool = False,
) -> None:
    values: dict[str, object] = {
        "current_step": next_step,
        "updated_at": func.current_timestamp(),
    }
    if clear_storage_key:
        values["storage_key"] = None
    statement = (
        update(DocumentDeletionJob)
        .where(
            DocumentDeletionJob.document_id == document_id,
            DocumentDeletionJob.user_id == user_id,
            DocumentDeletionJob.status == RUNNING,
            DocumentDeletionJob.lease_token == lease_token,
            DocumentDeletionJob.current_step == expected_step,
        )
        .values(**values)
        .returning(DocumentDeletionJob.id)
        .execution_options(synchronize_session=False)
    )
    try:
        if db.scalar(statement) is None:
            db.rollback()
            raise DocumentDeletionConflictError(
                "Document deletion lease is no longer owned by this worker."
            )
        db.commit()
    except DocumentDeletionConflictError:
        raise
    except SQLAlchemyError:
        _safe_rollback(db)
        raise DocumentDeletionInfrastructureError(
            "Document deletion progress could not be saved."
        ) from None


def _mark_failed(
    db: Session,
    *,
    document_id: int,
    user_id: int,
    lease_token: UUID,
    error_code: str,
) -> None:
    statement = (
        update(DocumentDeletionJob)
        .where(
            DocumentDeletionJob.document_id == document_id,
            DocumentDeletionJob.user_id == user_id,
            DocumentDeletionJob.status == RUNNING,
            DocumentDeletionJob.lease_token == lease_token,
        )
        .values(
            status=FAILED,
            lease_token=None,
            lease_expires_at=None,
            last_error_code=error_code,
            last_error_at=func.current_timestamp(),
            updated_at=func.current_timestamp(),
        )
        .returning(DocumentDeletionJob.id)
        .execution_options(synchronize_session=False)
    )
    try:
        if db.scalar(statement) is None:
            db.rollback()
            raise DocumentDeletionConflictError(
                "Document deletion lease is no longer owned by this worker."
            )
        db.commit()
    except DocumentDeletionConflictError:
        raise
    except SQLAlchemyError:
        _safe_rollback(db)
        raise DocumentDeletionInfrastructureError(
            "Document deletion failure state could not be saved."
        ) from None


def _delete_database_records(
    db: Session,
    *,
    document_id: int,
    user_id: int,
    lease_token: UUID,
) -> None:
    try:
        document = db.scalar(
            select(Document)
            .where(Document.id == document_id, Document.user_id == user_id)
            .with_for_update()
        )
        job = db.scalar(
            select(DocumentDeletionJob)
            .where(
                DocumentDeletionJob.document_id == document_id,
                DocumentDeletionJob.user_id == user_id,
                DocumentDeletionJob.status == RUNNING,
                DocumentDeletionJob.current_step == DATABASE_DELETE,
                DocumentDeletionJob.lease_token == lease_token,
            )
            .with_for_update()
        )
        if job is None:
            db.rollback()
            raise DocumentDeletionConflictError(
                "Document deletion lease is no longer owned by this worker."
            )
        if document is not None:
            db.execute(
                delete(Document).where(
                    Document.id == document_id,
                    Document.user_id == user_id,
                )
            )
        job.status = COMPLETED
        job.current_step = DONE
        job.lease_token = None
        job.lease_expires_at = None
        job.last_error_code = None
        job.last_error_at = None
        job.completed_at = datetime.now(timezone.utc)
        job.updated_at = datetime.now(timezone.utc)
        db.commit()
    except DocumentDeletionConflictError:
        raise
    except SQLAlchemyError:
        _safe_rollback(db)
        try:
            _mark_failed(
                db,
                document_id=document_id,
                user_id=user_id,
                lease_token=lease_token,
                error_code="database_delete_failed",
            )
        except DocumentDeletionError:
            pass
        raise DocumentDeletionInfrastructureError(
            "Document database records could not be deleted."
        ) from None


def _claimable_job_predicate() -> ColumnElement[bool]:
    return or_(
        DocumentDeletionJob.status.in_((PENDING, FAILED)),
        (
            (DocumentDeletionJob.status == RUNNING)
            & (DocumentDeletionJob.lease_expires_at <= func.current_timestamp())
        ),
    )


def _validate_identifier(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise DocumentDeletionNotFoundError("Document was not found.")


def _validate_lease_seconds(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("lease_seconds must be a positive integer.")


def _safe_rollback(db: Session) -> None:
    try:
        db.rollback()
    except SQLAlchemyError:
        pass
