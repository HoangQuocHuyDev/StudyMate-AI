"""Tests for the ordered chat message model and migration chain."""

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
from app.models.chat_message import ChatMessage
from app.models.chat_session import ChatSession
from app.models.document import Document
from app.models.user import User


@pytest.fixture
def chat_message_database() -> Iterator[sessionmaker[Session]]:
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
    metadata.create_all(database_engine)
    factory = sessionmaker(
        bind=database_engine,
        autoflush=False,
        expire_on_commit=False,
    )
    yield factory
    database_engine.dispose()


def add_chat_session(factory: sessionmaker[Session]) -> None:
    now = datetime.now(timezone.utc)
    with factory() as session:
        session.add(
            User(
                id=11,
                full_name="Message Test User",
                username="message_test_user",
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
                user_id=11,
                title="Machine Learning Notes",
                original_filename="ml.docx",
                storage_key="users/11/chat-message-test",
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
                title="Review machine learning",
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()


def make_message(
    sequence_no: int = 0,
    *,
    role: str = "USER",
    content: str = "What is supervised learning?",
) -> ChatMessage:
    return ChatMessage(
        session_id=1,
        sequence_no=sequence_no,
        role=role,
        content=content,
    )


def test_model_metadata_matches_chat_message_schema() -> None:
    table = ChatMessage.__table__

    assert list(table.c.keys()) == [
        "id",
        "session_id",
        "sequence_no",
        "role",
        "content",
        "created_at",
    ]
    assert table.c.id.type.python_type is int
    assert table.c.session_id.nullable is False
    assert table.c.sequence_no.nullable is False
    assert table.c.role.type.length == 20
    assert table.c.content.nullable is False
    assert table.c.created_at.type.timezone is True
    assert table.c.created_at.server_default is not None
    assert {
        constraint.name for constraint in table.constraints if constraint.name
    } >= {
        "uq_chat_messages_session_id_sequence_no",
        "fk_chat_messages_session_id_chat_sessions",
        "ck_chat_messages_sequence_no_nonnegative",
        "ck_chat_messages_role",
        "ck_chat_messages_content_nonblank",
    }
    assert not table.indexes
    assert "chat_messages" in Base.metadata.tables


def test_relationship_orders_messages_by_sequence_number(
    chat_message_database: sessionmaker[Session],
) -> None:
    add_chat_session(chat_message_database)
    with chat_message_database() as session:
        session.add_all(
            [
                make_message(2, role="ASSISTANT", content="Third message"),
                make_message(0, content="First message"),
                make_message(1, role="ASSISTANT", content="Second message"),
            ]
        )
        session.commit()

    with chat_message_database() as session:
        chat_session = session.get(ChatSession, 1)
        assert chat_session is not None
        assert [message.sequence_no for message in chat_session.messages] == [0, 1, 2]
        assert all(message.session is chat_session for message in chat_session.messages)


def test_unique_session_and_sequence_number_is_enforced(
    chat_message_database: sessionmaker[Session],
) -> None:
    add_chat_session(chat_message_database)
    with chat_message_database() as session:
        session.add_all([make_message(), make_message(content="Duplicate order")])
        with pytest.raises(IntegrityError):
            session.commit()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("sequence_no", -1),
        ("role", "SYSTEM"),
        ("content", "   "),
    ],
)
def test_check_constraints_reject_invalid_values(
    chat_message_database: sessionmaker[Session],
    field: str,
    value: int | str,
) -> None:
    add_chat_session(chat_message_database)
    message = make_message()
    setattr(message, field, value)
    with chat_message_database() as session:
        session.add(message)
        with pytest.raises(IntegrityError):
            session.commit()


def test_foreign_key_rejects_missing_session(
    chat_message_database: sessionmaker[Session],
) -> None:
    with chat_message_database() as session:
        session.add(make_message())
        with pytest.raises(IntegrityError):
            session.commit()


def test_database_cascade_delete_removes_messages(
    chat_message_database: sessionmaker[Session],
) -> None:
    add_chat_session(chat_message_database)
    with chat_message_database() as session:
        session.add(make_message())
        session.commit()
        session.execute(delete(ChatSession).where(ChatSession.id == 1))
        session.commit()

    with chat_message_database() as session:
        assert session.scalar(select(ChatMessage.id)) is None
        inspector = inspect(session.get_bind())
        foreign_key = inspector.get_foreign_keys("chat_messages")[0]
        assert foreign_key["options"]["ondelete"] == "CASCADE"


def test_migration_revision_chain_is_linear() -> None:
    migration = import_module(
        "migrations.versions.e4b7c2d9a631_create_chat_messages_table"
    )

    assert migration.revision == "e4b7c2d9a631"
    assert migration.down_revision == "d8f4a1c6b209"
    assert migration.branch_labels is None
    assert migration.depends_on is None
