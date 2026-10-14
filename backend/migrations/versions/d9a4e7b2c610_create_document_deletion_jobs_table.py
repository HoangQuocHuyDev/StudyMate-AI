"""create_document_deletion_jobs_table

Revision ID: d9a4e7b2c610
Revises: c8f1a6d3e905
Create Date: 2026-10-13

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "d9a4e7b2c610"
down_revision: str | Sequence[str] | None = "c8f1a6d3e905"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create durable document deletion workflow state."""

    op.create_table(
        "document_deletion_jobs",
        sa.Column(
            "id",
            sa.BigInteger(),
            sa.Identity(always=False),
            nullable=False,
        ),
        sa.Column("document_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default=sa.text("'PENDING'"),
            nullable=False,
        ),
        sa.Column(
            "current_step",
            sa.String(length=30),
            server_default=sa.text("'VECTOR_CLEANUP'"),
            nullable=False,
        ),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("lease_token", sa.Uuid(), nullable=True),
        sa.Column(
            "lease_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "last_error_code",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column(
            "last_error_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.CheckConstraint(
            "document_id > 0",
            name="ck_document_deletion_jobs_document_id_positive",
        ),
        sa.CheckConstraint(
            "user_id > 0",
            name="ck_document_deletion_jobs_user_id_positive",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name="ck_document_deletion_jobs_attempt_count_nonnegative",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'FAILED', 'COMPLETED')",
            name="ck_document_deletion_jobs_status",
        ),
        sa.CheckConstraint(
            "current_step IN "
            "('VECTOR_CLEANUP', 'FILE_CLEANUP', 'DATABASE_DELETE', 'DONE')",
            name="ck_document_deletion_jobs_current_step",
        ),
        sa.CheckConstraint(
            "storage_key IS NULL OR char_length(btrim(storage_key)) > 0",
            name="ck_document_deletion_jobs_storage_key_nonblank",
        ),
        sa.CheckConstraint(
            "last_error_code IS NULL "
            "OR char_length(btrim(last_error_code)) > 0",
            name="ck_document_deletion_jobs_last_error_code_nonblank",
        ),
        sa.CheckConstraint(
            "(status = 'RUNNING' "
            "AND lease_token IS NOT NULL "
            "AND lease_expires_at IS NOT NULL) "
            "OR (status <> 'RUNNING' "
            "AND lease_token IS NULL "
            "AND lease_expires_at IS NULL)",
            name="ck_document_deletion_jobs_lease_consistency",
        ),
        sa.CheckConstraint(
            "(status = 'COMPLETED' "
            "AND current_step = 'DONE' "
            "AND completed_at IS NOT NULL) "
            "OR (status <> 'COMPLETED' "
            "AND current_step <> 'DONE' "
            "AND completed_at IS NULL)",
            name="ck_document_deletion_jobs_completion_consistency",
        ),
        sa.CheckConstraint(
            "storage_key IS NOT NULL "
            "OR current_step IN ('DATABASE_DELETE', 'DONE')",
            name="ck_document_deletion_jobs_storage_key_step",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_id",
            name="uq_document_deletion_jobs_document_id",
        ),
    )
    op.create_index(
        "uq_document_deletion_jobs_storage_key_not_null",
        "document_deletion_jobs",
        ["storage_key"],
        unique=True,
        postgresql_where=sa.text("storage_key IS NOT NULL"),
    )
    op.create_index(
        "ix_document_deletion_jobs_retryable",
        "document_deletion_jobs",
        ["status", "updated_at", "id"],
        unique=False,
        postgresql_where=sa.text("status IN ('PENDING', 'FAILED')"),
    )
    op.create_index(
        "ix_document_deletion_jobs_expired_lease",
        "document_deletion_jobs",
        ["lease_expires_at", "id"],
        unique=False,
        postgresql_where=sa.text("status = 'RUNNING'"),
    )


def downgrade() -> None:
    """Drop the job table only when no unfinished workflow remains."""

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM document_deletion_jobs
                WHERE status <> 'COMPLETED'
            ) THEN
                RAISE EXCEPTION
                    'Cannot downgrade: unfinished document deletion jobs exist';
            END IF;
        END
        $$
        """
    )
    op.drop_index(
        "ix_document_deletion_jobs_expired_lease",
        table_name="document_deletion_jobs",
    )
    op.drop_index(
        "ix_document_deletion_jobs_retryable",
        table_name="document_deletion_jobs",
    )
    op.drop_index(
        "uq_document_deletion_jobs_storage_key_not_null",
        table_name="document_deletion_jobs",
    )
    op.drop_table("document_deletion_jobs")
