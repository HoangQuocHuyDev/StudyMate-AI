"""Persisted chat session model for one study document."""

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
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


if TYPE_CHECKING:
    from app.models.chat_message import ChatMessage
    from app.models.document import Document


_BIGINT_ID = BigInteger().with_variant(Integer, "sqlite")


class ChatSession(Base):
    """One ordered conversation history belonging to a document."""

    __tablename__ = "chat_sessions"
    __table_args__ = (
        CheckConstraint(
            "char_length(btrim(title)) BETWEEN 1 AND 255",
            name="ck_chat_sessions_title_length",
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
            name="fk_chat_sessions_document_id_documents",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
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
    document: Mapped["Document"] = relationship(back_populates="chat_sessions")
    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ChatMessage.sequence_no",
    )


Index(
    "ix_chat_sessions_document_id_updated_at_desc",
    ChatSession.document_id,
    ChatSession.updated_at.desc(),
)
