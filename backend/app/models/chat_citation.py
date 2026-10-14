"""Persisted source citation for one assistant chat message."""

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
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


if TYPE_CHECKING:
    from app.models.chat_message import ChatMessage
    from app.models.document_chunk import DocumentChunk


_BIGINT_ID = BigInteger().with_variant(Integer, "sqlite")


class ChatCitation(Base):
    """An ordered link from one answer to one retrieved source chunk."""

    __tablename__ = "chat_citations"
    __table_args__ = (
        UniqueConstraint(
            "message_id",
            "document_chunk_id",
            name="uq_chat_citations_message_id_document_chunk_id",
        ),
        UniqueConstraint(
            "message_id",
            "citation_order",
            name="uq_chat_citations_message_id_citation_order",
        ),
        CheckConstraint(
            "citation_order >= 0",
            name="ck_chat_citations_citation_order_nonnegative",
        ),
        Index("ix_chat_citations_document_chunk_id", "document_chunk_id"),
    )

    id: Mapped[int] = mapped_column(
        _BIGINT_ID,
        Identity(),
        primary_key=True,
    )
    message_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "chat_messages.id",
            name="fk_chat_citations_message_id_chat_messages",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    document_chunk_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "document_chunks.id",
            name="fk_chat_citations_document_chunk_id_document_chunks",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    citation_order: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )
    message: Mapped["ChatMessage"] = relationship(back_populates="citations")
    document_chunk: Mapped["DocumentChunk"] = relationship(
        back_populates="citations"
    )
