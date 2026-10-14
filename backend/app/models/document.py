"""Document metadata model."""

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
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.db.base import Base


if TYPE_CHECKING:
    from app.models.chat_session import ChatSession
    from app.models.document_chunk import DocumentChunk
    from app.models.document_summary import DocumentSummary


class Document(Base):
    """Metadata for a study document owned by a user."""

    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("storage_key", name="uq_documents_storage_key"),
        CheckConstraint(
            "file_type IN ('PDF', 'DOCX', 'TXT')",
            name="ck_documents_file_type",
        ),
        CheckConstraint(
            "status IN ('UPLOADED', 'PROCESSING', 'READY', 'FAILED')",
            name="ck_documents_status",
        ),
        CheckConstraint(
            "file_size > 0",
            name="ck_documents_file_size_positive",
        ),
        CheckConstraint(
            "character_count IS NULL OR character_count >= 0",
            name="ck_documents_character_count_nonnegative",
        ),
        CheckConstraint(
            "page_count IS NULL OR page_count > 0",
            name="ck_documents_page_count_positive",
        ),
        CheckConstraint(
            "rag_status IN ('PENDING', 'INDEXING', 'READY', 'FAILED')",
            name="ck_documents_rag_status",
        ),
        Index("ix_documents_user_id", "user_id"),
        Index("ix_documents_user_id_created_at", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "users.id",
            name="fk_documents_user_id_users",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    file_type: Mapped[str] = mapped_column(String(10), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default="UPLOADED",
    )
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
    character_count: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )
    page_count: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    rag_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default="PENDING",
    )
    indexed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    chunks: Mapped[list["DocumentChunk"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="DocumentChunk.chunk_index",
    )
    summaries: Mapped[list["DocumentSummary"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="DocumentSummary.summary_type",
    )
    chat_sessions: Mapped[list["ChatSession"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    @validates("file_type")
    def validate_file_type(self, key: str, value: str) -> str:
        """Reject formats no longer supported by the application layer."""

        if value not in {"PDF", "DOCX"}:
            raise ValueError("Document file type must be PDF or DOCX.")
        return value
