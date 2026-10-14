"""create_chat_sessions_table

Revision ID: d8f4a1c6b209
Revises: c3e8b7f1a204
Create Date: 2026-10-12

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "d8f4a1c6b209"
down_revision: str | Sequence[str] | None = "c3e8b7f1a204"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create document-scoped chat sessions and their history index."""

    op.create_table(
        "chat_sessions",
        sa.Column(
            "id",
            sa.BigInteger(),
            sa.Identity(always=False),
            nullable=False,
        ),
        sa.Column("document_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
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
            "char_length(btrim(title)) BETWEEN 1 AND 255",
            name="ck_chat_sessions_title_length",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name="fk_chat_sessions_document_id_documents",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_chat_sessions_document_id_updated_at_desc",
        "chat_sessions",
        ["document_id", sa.text("updated_at DESC")],
        unique=False,
    )


def downgrade() -> None:
    """Drop only the chat sessions table and its history index."""

    op.drop_index(
        "ix_chat_sessions_document_id_updated_at_desc",
        table_name="chat_sessions",
    )
    op.drop_table("chat_sessions")
