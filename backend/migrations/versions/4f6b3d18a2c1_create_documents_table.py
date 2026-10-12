"""create_documents_table

Revision ID: 4f6b3d18a2c1
Revises: eb5373800717
Create Date: 2026-10-12

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "4f6b3d18a2c1"
down_revision: str | Sequence[str] | None = "eb5373800717"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the documents metadata table and its indexes."""
    op.create_table(
        "documents",
        sa.Column(
            "id",
            sa.BigInteger(),
            sa.Identity(always=False),
            nullable=False,
        ),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("file_type", sa.String(length=10), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="UPLOADED",
            nullable=False,
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
        sa.CheckConstraint(
            "file_size > 0",
            name="ck_documents_file_size_positive",
        ),
        sa.CheckConstraint(
            "file_type IN ('PDF', 'DOCX', 'TXT')",
            name="ck_documents_file_type",
        ),
        sa.CheckConstraint(
            "status IN ('UPLOADED', 'PROCESSING', 'READY', 'FAILED')",
            name="ck_documents_status",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_documents_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_key", name="uq_documents_storage_key"),
    )
    op.create_index(
        "ix_documents_user_id",
        "documents",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_documents_user_id_created_at",
        "documents",
        ["user_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    """Drop the documents metadata table and its indexes."""
    op.drop_index(
        "ix_documents_user_id_created_at",
        table_name="documents",
    )
    op.drop_index("ix_documents_user_id", table_name="documents")
    op.drop_table("documents")
