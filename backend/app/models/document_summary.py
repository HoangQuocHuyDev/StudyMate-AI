"""Persisted Gemini document summary model."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


if TYPE_CHECKING:
    from app.models.document import Document


_BIGINT_ID = BigInteger().with_variant(Integer, "sqlite")


class DocumentSummary(Base):
    """One cached summary type generated for a document."""

    __tablename__ = "document_summaries"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "summary_type",
            name="uq_document_summaries_document_id_summary_type",
        ),
        CheckConstraint(
            "summary_type IN ('SHORT', 'STANDARD', 'DETAILED')",
            name="ck_document_summaries_summary_type",
        ),
        CheckConstraint(
            "char_length(btrim(content)) > 0",
            name="ck_document_summaries_content_nonblank",
        ),
        CheckConstraint(
            "char_length(btrim(model_name)) > 0",
            name="ck_document_summaries_model_name_nonblank",
        ),
    )

    id: Mapped[int] = mapped_column(
        _BIGINT_ID,
        Identity(),
        primary_key=True,
    )
    document_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "documents.id",
            name="fk_document_summaries_document_id_documents",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    summary_type: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
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
    document: Mapped["Document"] = relationship(back_populates="summaries")
