"""create_document_summaries_table

Revision ID: c3e8b7f1a204
Revises: a7c9e2f4b681
Create Date: 2026-10-12

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "c3e8b7f1a204"
down_revision: str | Sequence[str] | None = "a7c9e2f4b681"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create cached document summaries."""

    op.create_table(
        "document_summaries",
        sa.Column(
            "id",
            sa.BigInteger(),
            sa.Identity(always=False),
            nullable=False,
        ),
        sa.Column("document_id", sa.BigInteger(), nullable=False),
        sa.Column("summary_type", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("model_name", sa.String(length=100), nullable=False),
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
            "char_length(btrim(content)) > 0",
            name="ck_document_summaries_content_nonblank",
        ),
        sa.CheckConstraint(
            "char_length(btrim(model_name)) > 0",
            name="ck_document_summaries_model_name_nonblank",
        ),
        sa.CheckConstraint(
            "summary_type IN ('SHORT', 'STANDARD', 'DETAILED')",
            name="ck_document_summaries_summary_type",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name="fk_document_summaries_document_id_documents",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_id",
            "summary_type",
            name="uq_document_summaries_document_id_summary_type",
        ),
    )


def downgrade() -> None:
    """Drop only the document summaries table."""

    op.drop_table("document_summaries")
