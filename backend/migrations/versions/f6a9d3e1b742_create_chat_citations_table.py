"""create_chat_citations_table

Revision ID: f6a9d3e1b742
Revises: e4b7c2d9a631
Create Date: 2026-10-12

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "f6a9d3e1b742"
down_revision: str | Sequence[str] | None = "e4b7c2d9a631"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create ordered source citations for chat messages."""

    op.create_table(
        "chat_citations",
        sa.Column(
            "id",
            sa.BigInteger(),
            sa.Identity(always=False),
            nullable=False,
        ),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("document_chunk_id", sa.BigInteger(), nullable=False),
        sa.Column("citation_order", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "citation_order >= 0",
            name="ck_chat_citations_citation_order_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["document_chunk_id"],
            ["document_chunks.id"],
            name="fk_chat_citations_document_chunk_id_document_chunks",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["chat_messages.id"],
            name="fk_chat_citations_message_id_chat_messages",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "message_id",
            "citation_order",
            name="uq_chat_citations_message_id_citation_order",
        ),
        sa.UniqueConstraint(
            "message_id",
            "document_chunk_id",
            name="uq_chat_citations_message_id_document_chunk_id",
        ),
    )
    op.create_index(
        "ix_chat_citations_document_chunk_id",
        "chat_citations",
        ["document_chunk_id"],
        unique=False,
    )


def downgrade() -> None:
    """Drop only the chat citations table and reverse-lookup index."""

    op.drop_index(
        "ix_chat_citations_document_chunk_id",
        table_name="chat_citations",
    )
    op.drop_table("chat_citations")
