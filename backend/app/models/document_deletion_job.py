"""Durable orchestration state for safe document deletion."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Identity,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


_BIGINT_ID = BigInteger().with_variant(Integer, "sqlite")


class DocumentDeletionJob(Base):
    """A retryable deletion workflow that outlives its source document."""

    __tablename__ = "document_deletion_jobs"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            name="uq_document_deletion_jobs_document_id",
        ),
        CheckConstraint(
            "document_id > 0",
            name="ck_document_deletion_jobs_document_id_positive",
        ),
        CheckConstraint(
            "user_id > 0",
            name="ck_document_deletion_jobs_user_id_positive",
        ),
        CheckConstraint(
            "attempt_count >= 0",
            name="ck_document_deletion_jobs_attempt_count_nonnegative",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'FAILED', 'COMPLETED')",
            name="ck_document_deletion_jobs_status",
        ),
        CheckConstraint(
            "current_step IN "
            "('VECTOR_CLEANUP', 'FILE_CLEANUP', 'DATABASE_DELETE', 'DONE')",
            name="ck_document_deletion_jobs_current_step",
        ),
        CheckConstraint(
            "storage_key IS NULL OR char_length(btrim(storage_key)) > 0",
            name="ck_document_deletion_jobs_storage_key_nonblank",
        ),
        CheckConstraint(
            "last_error_code IS NULL "
            "OR char_length(btrim(last_error_code)) > 0",
            name="ck_document_deletion_jobs_last_error_code_nonblank",
        ),
        CheckConstraint(
            "(status = 'RUNNING' "
            "AND lease_token IS NOT NULL "
            "AND lease_expires_at IS NOT NULL) "
            "OR (status <> 'RUNNING' "
            "AND lease_token IS NULL "
            "AND lease_expires_at IS NULL)",
            name="ck_document_deletion_jobs_lease_consistency",
        ),
        CheckConstraint(
            "(status = 'COMPLETED' "
            "AND current_step = 'DONE' "
            "AND completed_at IS NOT NULL) "
            "OR (status <> 'COMPLETED' "
            "AND current_step <> 'DONE' "
            "AND completed_at IS NULL)",
            name="ck_document_deletion_jobs_completion_consistency",
        ),
        CheckConstraint(
            "storage_key IS NOT NULL "
            "OR current_step IN ('DATABASE_DELETE', 'DONE')",
            name="ck_document_deletion_jobs_storage_key_step",
        ),
        Index(
            "uq_document_deletion_jobs_storage_key_not_null",
            "storage_key",
            unique=True,
            postgresql_where=text("storage_key IS NOT NULL"),
        ),
        Index(
            "ix_document_deletion_jobs_retryable",
            "status",
            "updated_at",
            "id",
            postgresql_where=text("status IN ('PENDING', 'FAILED')"),
        ),
        Index(
            "ix_document_deletion_jobs_expired_lease",
            "lease_expires_at",
            "id",
            postgresql_where=text("status = 'RUNNING'"),
        ),
    )

    id: Mapped[int] = mapped_column(
        _BIGINT_ID,
        Identity(),
        primary_key=True,
    )
    document_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default="PENDING",
    )
    current_step: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default="VECTOR_CLEANUP",
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
    )
    lease_token: Mapped[UUID | None] = mapped_column(Uuid(), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_error_code: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    last_error_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
