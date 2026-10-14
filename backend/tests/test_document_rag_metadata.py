"""Tests for additive document processing and RAG metadata."""

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
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.document import Document
from app.models.user import User


@pytest.fixture
def document_database() -> Iterator[sessionmaker[Session]]:
    database_engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
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
    metadata.create_all(database_engine)
    factory = sessionmaker(
        bind=database_engine,
        autoflush=False,
        expire_on_commit=False,
    )
    yield factory
    database_engine.dispose()


def add_user(factory: sessionmaker[Session]) -> None:
    with factory() as session:
        session.add(
            User(
                id=17,
                full_name="RAG Metadata User",
                username="rag_metadata_user",
                password_hash="test-only-hash",
                role="USER",
                is_active=True,
                created_at=datetime.now(timezone.utc),
            )
        )
        session.commit()


def make_document(**overrides: object) -> Document:
    now = datetime.now(timezone.utc)
    values: dict[str, object] = {
        "id": 1,
        "user_id": 17,
        "title": "RAG Metadata",
        "original_filename": "rag-metadata.docx",
        "storage_key": "users/17/rag-metadata-test",
        "file_type": "DOCX",
        "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "file_size": 100,
        "status": "READY",
        "created_at": now,
        "updated_at": now,
    }
    values.update(overrides)
    return Document(**values)


def test_model_has_exact_rag_metadata_columns_and_constraints() -> None:
    table = Document.__table__

    assert table.c.character_count.type.python_type is int
    assert table.c.character_count.nullable is True
    assert table.c.page_count.type.python_type is int
    assert table.c.page_count.nullable is True
    assert table.c.processed_at.type.timezone is True
    assert table.c.processed_at.nullable is True
    assert table.c.rag_status.type.length == 20
    assert table.c.rag_status.nullable is False
    assert str(table.c.rag_status.server_default.arg) == "PENDING"
    assert table.c.indexed_at.type.timezone is True
    assert table.c.indexed_at.nullable is True
    assert {
        constraint.name for constraint in table.constraints if constraint.name
    } >= {
        "ck_documents_character_count_nonnegative",
        "ck_documents_page_count_positive",
        "ck_documents_rag_status",
    }


def test_model_rejects_txt_at_the_application_layer() -> None:
    with pytest.raises(ValueError, match="PDF or DOCX"):
        make_document(file_type="TXT")


def test_legacy_document_gets_pending_without_invented_metadata(
    document_database: sessionmaker[Session],
) -> None:
    add_user(document_database)
    with document_database() as session:
        session.add(make_document())
        session.commit()

    with document_database() as session:
        document = session.get(Document, 1)
        assert document is not None
        assert document.rag_status == "PENDING"
        assert document.character_count is None
        assert document.page_count is None
        assert document.processed_at is None
        assert document.indexed_at is None


@pytest.mark.parametrize("rag_status", ["PENDING", "INDEXING", "READY", "FAILED"])
def test_valid_rag_statuses_are_accepted(
    document_database: sessionmaker[Session],
    rag_status: str,
) -> None:
    add_user(document_database)
    with document_database() as session:
        session.add(make_document(rag_status=rag_status))
        session.commit()
        assert session.get(Document, 1).rag_status == rag_status


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("character_count", -1),
        ("page_count", 0),
        ("page_count", -1),
        ("rag_status", "COMPLETE"),
    ],
)
def test_invalid_rag_metadata_is_rejected(
    document_database: sessionmaker[Session],
    field: str,
    value: int | str,
) -> None:
    add_user(document_database)
    document = make_document()
    setattr(document, field, value)
    with document_database() as session:
        session.add(document)
        with pytest.raises(IntegrityError):
            session.commit()


def test_zero_character_count_and_positive_page_count_are_accepted(
    document_database: sessionmaker[Session],
) -> None:
    add_user(document_database)
    with document_database() as session:
        session.add(make_document(character_count=0, page_count=1))
        session.commit()

        document = session.get(Document, 1)
        assert document.character_count == 0
        assert document.page_count == 1


def test_existing_relationships_remain_registered() -> None:
    relationship_names = set(Document.__mapper__.relationships.keys())

    assert relationship_names == {"chunks", "summaries", "chat_sessions"}


def test_migration_is_additive_and_safe_for_existing_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = import_module(
        "migrations.versions.b7d2e9f4c816_add_rag_metadata_to_documents"
    )

    class OperationRecorder:
        def __init__(self) -> None:
            self.columns: list[tuple[str, object]] = []
            self.checks: list[tuple[str, str, str]] = []

        def add_column(self, table_name: str, column: object) -> None:
            self.columns.append((table_name, column))

        def create_check_constraint(
            self,
            name: str,
            table_name: str,
            condition: str,
        ) -> None:
            self.checks.append((name, table_name, condition))

    recorder = OperationRecorder()
    monkeypatch.setattr(migration, "op", recorder)
    migration.upgrade()

    assert [column.name for _, column in recorder.columns] == [
        "character_count",
        "page_count",
        "processed_at",
        "rag_status",
        "indexed_at",
    ]
    assert all(table_name == "documents" for table_name, _ in recorder.columns)
    columns = {column.name: column for _, column in recorder.columns}
    assert columns["character_count"].nullable is True
    assert columns["page_count"].nullable is True
    assert columns["processed_at"].nullable is True
    assert columns["indexed_at"].nullable is True
    assert columns["rag_status"].nullable is False
    assert str(columns["rag_status"].server_default.arg) == "PENDING"
    assert len(recorder.checks) == 3
    assert all(table_name == "documents" for _, table_name, _ in recorder.checks)


def test_migration_revision_chain_is_linear() -> None:
    migration = import_module(
        "migrations.versions.b7d2e9f4c816_add_rag_metadata_to_documents"
    )

    assert migration.revision == "b7d2e9f4c816"
    assert migration.down_revision == "f6a9d3e1b742"
    assert migration.branch_labels is None
    assert migration.depends_on is None
