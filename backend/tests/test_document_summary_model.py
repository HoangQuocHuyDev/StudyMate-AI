"""Tests for the persistent document summary model."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone

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
from app.models.document import Document
from app.models.document_summary import DocumentSummary
from app.models.user import User


@pytest.fixture
def summary_database() -> Iterator[sessionmaker[Session]]:
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
    DocumentSummary.__table__.to_metadata(metadata)
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
                id=7,
                full_name="Test User",
                username="test_user",
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
                user_id=7,
                title="Artificial Intelligence",
                original_filename="ai.docx",
                storage_key="users/7/document-summary-test",
                file_type="DOCX",
                mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                file_size=100,
                status="READY",
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()


def make_summary(
    *,
    summary_type: str = "STANDARD",
    content: str = "A concise study summary.",
    model_name: str = "gemini-test-model",
) -> DocumentSummary:
    return DocumentSummary(
        document_id=1,
        summary_type=summary_type,
        content=content,
        model_name=model_name,
    )


def test_model_metadata_matches_document_summary_schema() -> None:
    table = DocumentSummary.__table__

    assert table.c.id.type.python_type is int
    assert table.c.document_id.nullable is False
    assert table.c.summary_type.type.length == 20
    assert table.c.content.nullable is False
    assert table.c.model_name.type.length == 100
    assert table.c.created_at.type.timezone is True
    assert table.c.updated_at.type.timezone is True
    assert table.c.created_at.server_default is not None
    assert table.c.updated_at.server_default is not None
    assert {
        constraint.name for constraint in table.constraints if constraint.name
    } >= {
        "uq_document_summaries_document_id_summary_type",
        "fk_document_summaries_document_id_documents",
        "ck_document_summaries_summary_type",
        "ck_document_summaries_content_nonblank",
        "ck_document_summaries_model_name_nonblank",
    }
    assert not table.indexes
    assert "document_summaries" in Base.metadata.tables


def test_relationship_is_bidirectional_and_ordered(
    summary_database: sessionmaker[Session],
) -> None:
    add_document(summary_database)
    with summary_database() as session:
        session.add_all(
            [
                make_summary(summary_type="STANDARD"),
                make_summary(summary_type="SHORT", content="Short summary."),
            ]
        )
        session.commit()

    with summary_database() as session:
        document = session.get(Document, 1)
        assert document is not None
        assert [summary.summary_type for summary in document.summaries] == [
            "SHORT",
            "STANDARD",
        ]
        assert all(summary.document is document for summary in document.summaries)


def test_unique_document_and_summary_type_is_enforced(
    summary_database: sessionmaker[Session],
) -> None:
    add_document(summary_database)
    with summary_database() as session:
        session.add_all([make_summary(), make_summary(content="Another summary.")])
        with pytest.raises(IntegrityError):
            session.commit()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("summary_type", "CUSTOM"),
        ("content", "   "),
        ("model_name", "  "),
    ],
)
def test_check_constraints_reject_invalid_values(
    summary_database: sessionmaker[Session],
    field: str,
    value: str,
) -> None:
    add_document(summary_database)
    summary = make_summary()
    setattr(summary, field, value)
    with summary_database() as session:
        session.add(summary)
        with pytest.raises(IntegrityError):
            session.commit()


def test_foreign_key_rejects_missing_document(
    summary_database: sessionmaker[Session],
) -> None:
    with summary_database() as session:
        session.add(make_summary())
        with pytest.raises(IntegrityError):
            session.commit()


def test_database_cascade_delete_removes_summaries(
    summary_database: sessionmaker[Session],
) -> None:
    add_document(summary_database)
    with summary_database() as session:
        session.add(make_summary())
        session.commit()
        session.execute(delete(Document).where(Document.id == 1))
        session.commit()

    with summary_database() as session:
        assert session.scalar(select(DocumentSummary.id)) is None
        inspector = inspect(session.get_bind())
        foreign_key = inspector.get_foreign_keys("document_summaries")[0]
        assert foreign_key["options"]["ondelete"] == "CASCADE"
