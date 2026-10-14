"""Tests for the chat citation model and migration chain."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone
from importlib import import_module

import pytest
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    delete,
    event,
    inspect,
    select,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.chat_citation import ChatCitation
from app.models.chat_message import ChatMessage
from app.models.chat_session import ChatSession
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.user import User


@pytest.fixture
def citation_database() -> Iterator[sessionmaker[Session]]:
    database_engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(database_engine, "connect")
    def configure_sqlite(dbapi_connection: object, record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    metadata = MetaData()
    Table(
        "users",
        metadata,
        Column("id", BigInteger, primary_key=True),
        Column("full_name", String(100), nullable=False),
        Column("username", String(30), nullable=False),
        Column("password_hash", Text, nullable=False),
        Column("role", String(10), nullable=False),
        Column("is_active", Boolean, nullable=False),
        Column("token_version", BigInteger, nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
    )
    Document.__table__.to_metadata(metadata)
    ChatSession.__table__.to_metadata(metadata)
    ChatMessage.__table__.to_metadata(metadata)
    DocumentChunk.__table__.to_metadata(metadata)
    ChatCitation.__table__.to_metadata(metadata)
    metadata.create_all(database_engine)
    factory = sessionmaker(
        bind=database_engine,
        autoflush=False,
        expire_on_commit=False,
    )
    yield factory
    database_engine.dispose()


def add_citation_graph(factory: sessionmaker[Session]) -> None:
    now = datetime.now(timezone.utc)
    with factory() as session:
        session.add(
            User(
                id=13,
                full_name="Citation Test User",
                username="citation_test_user",
                password_hash="test-only-hash",
                role="USER",
                is_active=True,
                created_at=now,
            )
        )
        session.flush()
        session.add(
            Document(
                id=1,
                user_id=13,
                title="RAG Sources",
                original_filename="rag-sources.docx",
                storage_key="users/13/chat-citation-test",
                file_type="DOCX",
                mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                file_size=100,
                status="READY",
                created_at=now,
                updated_at=now,
            )
        )
        session.flush()
        session.add(
            ChatSession(
                id=1,
                document_id=1,
                title="Review sources",
                created_at=now,
                updated_at=now,
            )
        )
        session.add_all(
            [
                DocumentChunk(
                    id=1,
                    document_id=1,
                    chunk_index=0,
                    content="First source chunk",
                    start_char=0,
                    end_char=18,
                    character_count=18,
                    page_number=None,
                    created_at=now,
                ),
                DocumentChunk(
                    id=2,
                    document_id=1,
                    chunk_index=1,
                    content="Second source chunk",
                    start_char=18,
                    end_char=37,
                    character_count=19,
                    page_number=None,
                    created_at=now,
                ),
            ]
        )
        session.flush()
        session.add(
            ChatMessage(
                id=1,
                session_id=1,
                sequence_no=0,
                role="ASSISTANT",
                content="An answer with sources.",
                created_at=now,
            )
        )
        session.commit()


def make_citation(
    citation_order: int = 0,
    *,
    document_chunk_id: int = 1,
) -> ChatCitation:
    return ChatCitation(
        message_id=1,
        document_chunk_id=document_chunk_id,
        citation_order=citation_order,
    )


def test_model_metadata_matches_chat_citation_schema() -> None:
    table = ChatCitation.__table__

    assert list(table.c.keys()) == [
        "id",
        "message_id",
        "document_chunk_id",
        "citation_order",
        "created_at",
    ]
    assert table.c.id.type.python_type is int
    assert table.c.message_id.nullable is False
    assert table.c.document_chunk_id.nullable is False
    assert table.c.citation_order.nullable is False
    assert table.c.created_at.type.timezone is True
    assert table.c.created_at.server_default is not None
    assert {
        constraint.name for constraint in table.constraints if constraint.name
    } >= {
        "uq_chat_citations_message_id_document_chunk_id",
        "uq_chat_citations_message_id_citation_order",
        "fk_chat_citations_message_id_chat_messages",
        "fk_chat_citations_document_chunk_id_document_chunks",
        "ck_chat_citations_citation_order_nonnegative",
    }
    assert {index.name for index in table.indexes} == {
        "ix_chat_citations_document_chunk_id"
    }
    assert "chat_citations" in Base.metadata.tables


def test_relationships_are_bidirectional_and_ordered(
    citation_database: sessionmaker[Session],
) -> None:
    add_citation_graph(citation_database)
    with citation_database() as session:
        session.add_all(
            [
                make_citation(1, document_chunk_id=2),
                make_citation(0, document_chunk_id=1),
            ]
        )
        session.commit()

    with citation_database() as session:
        message = session.get(ChatMessage, 1)
        first_chunk = session.get(DocumentChunk, 1)
        assert message is not None
        assert first_chunk is not None
        assert [citation.citation_order for citation in message.citations] == [0, 1]
        assert all(citation.message is message for citation in message.citations)
        assert len(first_chunk.citations) == 1
        assert first_chunk.citations[0].document_chunk is first_chunk


def test_unique_message_and_chunk_is_enforced(
    citation_database: sessionmaker[Session],
) -> None:
    add_citation_graph(citation_database)
    with citation_database() as session:
        session.add_all([make_citation(0), make_citation(1)])
        with pytest.raises(IntegrityError):
            session.commit()


def test_unique_message_and_citation_order_is_enforced(
    citation_database: sessionmaker[Session],
) -> None:
    add_citation_graph(citation_database)
    with citation_database() as session:
        session.add_all(
            [make_citation(0, document_chunk_id=1), make_citation(0, document_chunk_id=2)]
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_negative_citation_order_is_rejected(
    citation_database: sessionmaker[Session],
) -> None:
    add_citation_graph(citation_database)
    with citation_database() as session:
        session.add(make_citation(-1))
        with pytest.raises(IntegrityError):
            session.commit()


@pytest.mark.parametrize(
    ("message_id", "document_chunk_id"),
    [(999, 1), (1, 999)],
)
def test_foreign_keys_reject_missing_parents(
    citation_database: sessionmaker[Session],
    message_id: int,
    document_chunk_id: int,
) -> None:
    add_citation_graph(citation_database)
    citation = make_citation(document_chunk_id=document_chunk_id)
    citation.message_id = message_id
    with citation_database() as session:
        session.add(citation)
        with pytest.raises(IntegrityError):
            session.commit()


@pytest.mark.parametrize("parent", ["message", "chunk"])
def test_database_cascade_delete_removes_citations(
    citation_database: sessionmaker[Session],
    parent: str,
) -> None:
    add_citation_graph(citation_database)
    with citation_database() as session:
        session.add(make_citation())
        session.commit()
        if parent == "message":
            session.execute(delete(ChatMessage).where(ChatMessage.id == 1))
        else:
            session.execute(delete(DocumentChunk).where(DocumentChunk.id == 1))
        session.commit()

    with citation_database() as session:
        assert session.scalar(select(ChatCitation.id)) is None
        foreign_keys = inspect(session.get_bind()).get_foreign_keys(
            "chat_citations"
        )
        assert all(
            foreign_key["options"]["ondelete"] == "CASCADE"
            for foreign_key in foreign_keys
        )


def test_migration_revision_chain_is_linear() -> None:
    migration = import_module(
        "migrations.versions.f6a9d3e1b742_create_chat_citations_table"
    )

    assert migration.revision == "f6a9d3e1b742"
    assert migration.down_revision == "e4b7c2d9a631"
    assert migration.branch_labels is None
    assert migration.depends_on is None
