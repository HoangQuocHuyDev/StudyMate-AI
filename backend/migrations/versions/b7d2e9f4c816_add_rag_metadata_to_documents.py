"""add_rag_metadata_to_documents

Revision ID: b7d2e9f4c816
Revises: f6a9d3e1b742
Create Date: 2026-10-12

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "b7d2e9f4c816"
down_revision: str | Sequence[str] | None = "f6a9d3e1b742"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add nullable processing metadata and an explicit RAG lifecycle."""

    op.add_column(
        "documents",
        sa.Column("character_count", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column("page_count", sa.Integer(), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column(
            "rag_status",
            sa.String(length=20),
            server_default="PENDING",
            nullable=False,
        ),
    )
    op.add_column(
        "documents",
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_documents_character_count_nonnegative",
        "documents",
        "character_count IS NULL OR character_count >= 0",
    )
    op.create_check_constraint(
        "ck_documents_page_count_positive",
        "documents",
        "page_count IS NULL OR page_count > 0",
    )
    op.create_check_constraint(
        "ck_documents_rag_status",
        "documents",
        "rag_status IN ('PENDING', 'INDEXING', 'READY', 'FAILED')",
    )


def downgrade() -> None:
    """Remove only the document RAG metadata added by this revision."""

    op.drop_constraint(
        "ck_documents_rag_status",
        "documents",
        type_="check",
    )
    op.drop_constraint(
        "ck_documents_page_count_positive",
        "documents",
        type_="check",
    )
    op.drop_constraint(
        "ck_documents_character_count_nonnegative",
        "documents",
        type_="check",
    )
    op.drop_column("documents", "indexed_at")
    op.drop_column("documents", "rag_status")
    op.drop_column("documents", "processed_at")
    op.drop_column("documents", "page_count")
    op.drop_column("documents", "character_count")
