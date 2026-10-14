"""Persisted message model for a document chat session."""

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
    from app.models.chat_citation import ChatCitation
    from app.models.chat_session import ChatSession


_BIGINT_ID = BigInteger().with_variant(Integer, "sqlite")


class ChatMessage(Base):
    """One user or assistant message in stable conversation order."""

    __tablename__ = "chat_messages"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "sequence_no",
            name="uq_chat_messages_session_id_sequence_no",
        ),
        CheckConstraint(
            "sequence_no >= 0",
            name="ck_chat_messages_sequence_no_nonnegative",
        ),
        CheckConstraint(
            "role IN ('USER', 'ASSISTANT')",
            name="ck_chat_messages_role",
        ),
        CheckConstraint(
            "char_length(btrim(content)) > 0",
            name="ck_chat_messages_content_nonblank",
        ),
    )

    id: Mapped[int] = mapped_column(
        _BIGINT_ID,
        Identity(),
        primary_key=True,
    )
    session_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "chat_sessions.id",
            name="fk_chat_messages_session_id_chat_sessions",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )
    session: Mapped["ChatSession"] = relationship(back_populates="messages")
    citations: Mapped[list["ChatCitation"]] = relationship(
        back_populates="message",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ChatCitation.citation_order",
    )
