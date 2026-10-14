"""Persisted text chunk model for processed study documents."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


if TYPE_CHECKING:
    from app.models.chat_citation import ChatCitation
    from app.models.document import Document


_BIGINT_ID = BigInteger().with_variant(Integer, "sqlite")


class DocumentChunk(Base):
    """One ordered, offset-safe text chunk belonging to a document."""

    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "chunk_index",
            name="uq_document_chunks_document_id_chunk_index",
        ),
        CheckConstraint(
            "chunk_index >= 0",
            name="ck_document_chunks_chunk_index_nonnegative",
        ),
        CheckConstraint(
            "start_char >= 0",
            name="ck_document_chunks_start_char_nonnegative",
        ),
        CheckConstraint(
            "end_char > start_char",
            name="ck_document_chunks_end_after_start",
        ),
        CheckConstraint(
            "character_count = end_char - start_char",
            name="ck_document_chunks_character_count_matches_offsets",
        ),
        CheckConstraint(
            "page_number IS NULL OR page_number >= 1",
            name="ck_document_chunks_page_number_positive",
        ),
        CheckConstraint(
            "length(content) > 0",
            name="ck_document_chunks_content_nonempty",
        ),
        Index("ix_document_chunks_document_id", "document_id"),
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
            name="fk_document_chunks_document_id_documents",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    start_char: Mapped[int] = mapped_column(Integer, nullable=False)
    end_char: Mapped[int] = mapped_column(Integer, nullable=False)
    character_count: Mapped[int] = mapped_column(Integer, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )
    document: Mapped["Document"] = relationship(back_populates="chunks")
    citations: Mapped[list["ChatCitation"]] = relationship(
        back_populates="document_chunk",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ChatCitation.citation_order",
    )
