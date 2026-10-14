"""create_chat_messages_table

Revision ID: e4b7c2d9a631
Revises: d8f4a1c6b209
Create Date: 2026-10-12

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "e4b7c2d9a631"
down_revision: str | Sequence[str] | None = "d8f4a1c6b209"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create ordered messages for document chat sessions."""

    op.create_table(
        "chat_messages",
        sa.Column(
            "id",
            sa.BigInteger(),
            sa.Identity(always=False),
            nullable=False,
        ),
        sa.Column("session_id", sa.BigInteger(), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "char_length(btrim(content)) > 0",
            name="ck_chat_messages_content_nonblank",
        ),
        sa.CheckConstraint(
            "role IN ('USER', 'ASSISTANT')",
            name="ck_chat_messages_role",
        ),
        sa.CheckConstraint(
            "sequence_no >= 0",
            name="ck_chat_messages_sequence_no_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["chat_sessions.id"],
            name="fk_chat_messages_session_id_chat_sessions",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "session_id",
            "sequence_no",
            name="uq_chat_messages_session_id_sequence_no",
        ),
    )


def downgrade() -> None:
    """Drop only the chat messages table."""

    op.drop_table("chat_messages")
