"""create_document_chunks_table

Revision ID: a7c9e2f4b681
Revises: 4f6b3d18a2c1
Create Date: 2026-10-12

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "a7c9e2f4b681"
down_revision: str | Sequence[str] | None = "4f6b3d18a2c1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create persistent document chunks and their lookup index."""

    op.create_table(
        "document_chunks",
        sa.Column(
            "id",
            sa.BigInteger(),
            sa.Identity(always=False),
            nullable=False,
        ),
        sa.Column("document_id", sa.BigInteger(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("start_char", sa.Integer(), nullable=False),
        sa.Column("end_char", sa.Integer(), nullable=False),
        sa.Column("character_count", sa.Integer(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "character_count = end_char - start_char",
            name="ck_document_chunks_character_count_matches_offsets",
        ),
        sa.CheckConstraint(
            "chunk_index >= 0",
            name="ck_document_chunks_chunk_index_nonnegative",
        ),
        sa.CheckConstraint(
            "length(content) > 0",
            name="ck_document_chunks_content_nonempty",
        ),
        sa.CheckConstraint(
            "end_char > start_char",
            name="ck_document_chunks_end_after_start",
        ),
        sa.CheckConstraint(
            "page_number IS NULL OR page_number >= 1",
            name="ck_document_chunks_page_number_positive",
        ),
        sa.CheckConstraint(
            "start_char >= 0",
            name="ck_document_chunks_start_char_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name="fk_document_chunks_document_id_documents",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_id",
            "chunk_index",
            name="uq_document_chunks_document_id_chunk_index",
        ),
    )
    op.create_index(
        "ix_document_chunks_document_id",
        "document_chunks",
        ["document_id"],
        unique=False,
    )


def downgrade() -> None:
    """Drop only the persistent document chunks table."""

    op.drop_index(
        "ix_document_chunks_document_id",
        table_name="document_chunks",
    )
    op.drop_table("document_chunks")
