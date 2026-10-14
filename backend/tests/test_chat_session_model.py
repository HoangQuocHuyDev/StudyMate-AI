"""Tests for the document-scoped chat session model and migration chain."""

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
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.schema import CreateIndex

from app.db.base import Base
from app.models.chat_session import ChatSession
from app.models.document import Document
from app.models.user import User


@pytest.fixture
def chat_session_database() -> Iterator[sessionmaker[Session]]:
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
    metadata.create_all(database_engine)
    factory = sessionmaker(
        bind=database_engine,
        autoflush=False,
        expire_on_commit=False,
    )
    yield factory
    database_engine.dispose()


def add_document(factory: sessionmaker[Session]) -> None:
    now = datetime.now(timezone.utc)
    with factory() as session:
        session.add(
            User(
                id=9,
                full_name="Chat Test User",
                username="chat_test_user",
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
                user_id=9,
                title="RAG Notes",
                original_filename="rag.docx",
                storage_key="users/9/chat-session-test",
                file_type="DOCX",
                mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                file_size=100,
                status="READY",
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()


def make_chat_session(title: str = "Review RAG concepts") -> ChatSession:
    return ChatSession(document_id=1, title=title)


def test_model_metadata_matches_chat_session_schema() -> None:
    table = ChatSession.__table__

    assert list(table.c.keys()) == [
        "id",
        "document_id",
        "title",
        "created_at",
        "updated_at",
    ]
    assert table.c.id.type.python_type is int
    assert table.c.document_id.nullable is False
    assert table.c.title.type.length == 255
    assert table.c.created_at.type.timezone is True
    assert table.c.updated_at.type.timezone is True
    assert table.c.created_at.server_default is not None
    assert table.c.updated_at.server_default is not None
    assert {
        constraint.name for constraint in table.constraints if constraint.name
    } >= {
        "fk_chat_sessions_document_id_documents",
        "ck_chat_sessions_title_length",
    }
    assert "chat_sessions" in Base.metadata.tables


def test_history_index_is_descending_and_not_duplicated() -> None:
    indexes = list(ChatSession.__table__.indexes)

    assert len(indexes) == 1
    assert indexes[0].name == "ix_chat_sessions_document_id_updated_at_desc"
    compiled = str(
        CreateIndex(indexes[0]).compile(dialect=postgresql.dialect())
    )
    assert compiled == (
        "CREATE INDEX ix_chat_sessions_document_id_updated_at_desc "
        "ON chat_sessions (document_id, updated_at DESC)"
    )


def test_relationship_is_bidirectional(
    chat_session_database: sessionmaker[Session],
) -> None:
    add_document(chat_session_database)
    with chat_session_database() as session:
        chat_session = make_chat_session()
        session.add(chat_session)
        session.commit()

    with chat_session_database() as session:
        document = session.get(Document, 1)
        assert document is not None
        assert len(document.chat_sessions) == 1
        assert document.chat_sessions[0].title == "Review RAG concepts"
        assert document.chat_sessions[0].document is document


@pytest.mark.parametrize("title", ["", "   ", "x" * 256])
def test_title_check_constraint_rejects_invalid_values(
    chat_session_database: sessionmaker[Session],
    title: str,
) -> None:
    add_document(chat_session_database)
    with chat_session_database() as session:
        session.add(make_chat_session(title))
        with pytest.raises(IntegrityError):
            session.commit()


def test_foreign_key_rejects_missing_document(
    chat_session_database: sessionmaker[Session],
) -> None:
    with chat_session_database() as session:
        session.add(make_chat_session())
        with pytest.raises(IntegrityError):
            session.commit()


def test_database_cascade_delete_removes_chat_sessions(
    chat_session_database: sessionmaker[Session],
) -> None:
    add_document(chat_session_database)
    with chat_session_database() as session:
        session.add(make_chat_session())
        session.commit()
        session.execute(delete(Document).where(Document.id == 1))
        session.commit()

    with chat_session_database() as session:
        assert session.scalar(select(ChatSession.id)) is None
        inspector = inspect(session.get_bind())
        foreign_key = inspector.get_foreign_keys("chat_sessions")[0]
        assert foreign_key["options"]["ondelete"] == "CASCADE"


def test_migration_revision_chain_is_linear() -> None:
    migration = import_module(
        "migrations.versions.d8f4a1c6b209_create_chat_sessions_table"
    )

    assert migration.revision == "d8f4a1c6b209"
    assert migration.down_revision == "c3e8b7f1a204"
    assert migration.branch_labels is None
    assert migration.depends_on is None
