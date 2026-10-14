"""Tests for the persistent document chunk model and repository."""

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
)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.document import Document
from app.models.document_deletion_job import DocumentDeletionJob
from app.models.document_chunk import DocumentChunk
from app.models.user import User
from app.services.document_chunk_repository import (
    DocumentChunkDocumentNotFoundError,
    DocumentChunkPersistenceError,
    DuplicateDocumentChunksError,
    InvalidDocumentChunkError,
    count_document_chunks,
    get_document_chunks,
    save_document_chunks,
)
from app.services.text_chunker import TextChunk


@pytest.fixture
def chunk_database() -> Iterator[tuple[sessionmaker[Session], object]]:
    database_engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(database_engine, "connect")
    def enable_sqlite_foreign_keys(dbapi_connection: object, record: object) -> None:
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
    DocumentDeletionJob.__table__.to_metadata(metadata)
    DocumentChunk.__table__.to_metadata(metadata)
    metadata.create_all(database_engine)
    factory = sessionmaker(
        bind=database_engine,
        autoflush=False,
        expire_on_commit=False,
    )
    yield factory, database_engine
    database_engine.dispose()


def add_document(
    factory: sessionmaker[Session],
    *,
    document_id: int = 1,
    user_id: int = 7,
) -> None:
    now = datetime.now(timezone.utc)
    with factory() as session:
        if session.get(User, user_id) is None:
            session.add(
                User(
                    id=user_id,
                    full_name=f"User {user_id}",
                    username=f"user_{user_id}",
                    password_hash="test-only-hash",
                    role="USER",
                    is_active=True,
                    created_at=now,
                )
            )
            session.flush()
        session.add(
            Document(
                id=document_id,
                user_id=user_id,
                title=f"Document {document_id}",
                original_filename=f"document-{document_id}.docx",
                storage_key=f"users/{user_id}/{document_id}",
                file_type="DOCX",
                mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                file_size=100,
                status="PROCESSING",
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()


def make_chunk(
    index: int,
    text: str,
    start_char: int,
    *,
    page_number: int | None = None,
) -> TextChunk:
    return TextChunk(
        index=index,
        text=text,
        start_char=start_char,
        end_char=start_char + len(text),
        character_count=len(text),
        page_number=page_number,
    )


def test_model_metadata_matches_persistent_chunk_schema() -> None:
    table = DocumentChunk.__table__

    assert table.c.id.type.python_type is int
    assert table.c.document_id.nullable is False
    assert table.c.content.nullable is False
    assert table.c.page_number.nullable is True
    assert {
        constraint.name for constraint in table.constraints if constraint.name
    } >= {
        "uq_document_chunks_document_id_chunk_index",
        "fk_document_chunks_document_id_documents",
        "ck_document_chunks_chunk_index_nonnegative",
        "ck_document_chunks_start_char_nonnegative",
        "ck_document_chunks_end_after_start",
        "ck_document_chunks_character_count_matches_offsets",
        "ck_document_chunks_page_number_positive",
        "ck_document_chunks_content_nonempty",
    }
    assert {index.name for index in table.indexes} == {
        "ix_document_chunks_document_id"
    }


def test_save_one_chunk_successfully(
    chunk_database: tuple[sessionmaker[Session], object],
) -> None:
    factory, _ = chunk_database
    add_document(factory)

    with factory() as session:
        saved_count = save_document_chunks(
            session,
            document_id=1,
            user_id=7,
            chunks=[make_chunk(0, "StudyMate", 0)],
        )
        session.commit()

    assert saved_count == 1
    with factory() as session:
        assert count_document_chunks(session, document_id=1, user_id=7) == 1


def test_save_multiple_chunks_and_count_them(
    chunk_database: tuple[sessionmaker[Session], object],
) -> None:
    factory, _ = chunk_database
    add_document(factory)
    chunks = [
        make_chunk(0, "alpha", 0),
        make_chunk(1, "beta", 5),
        make_chunk(2, "gamma", 9),
    ]

    with factory() as session:
        assert save_document_chunks(
            session,
            document_id=1,
            user_id=7,
            chunks=chunks,
        ) == 3
        session.commit()
    with factory() as session:
        assert count_document_chunks(session, document_id=1, user_id=7) == 3


def test_get_chunks_orders_by_chunk_index(
    chunk_database: tuple[sessionmaker[Session], object],
) -> None:
    factory, _ = chunk_database
    add_document(factory)
    now = datetime.now(timezone.utc)
    with factory() as session:
        session.add_all(
            [
                DocumentChunk(
                    document_id=1,
                    chunk_index=index,
                    content=value,
                    start_char=start,
                    end_char=start + len(value),
                    character_count=len(value),
                    page_number=None,
                    created_at=now,
                )
                for index, value, start in (
                    (2, "third", 10),
                    (0, "first", 0),
                    (1, "second", 5),
                )
            ]
        )
        session.commit()

    with factory() as session:
        stored = get_document_chunks(session, document_id=1, user_id=7)

    assert [chunk.chunk_index for chunk in stored] == [0, 1, 2]


def test_owner_can_read_but_another_user_cannot_read_or_count_chunks(
    chunk_database: tuple[sessionmaker[Session], object],
) -> None:
    factory, _ = chunk_database
    add_document(factory, document_id=1, user_id=7)
    add_document(factory, document_id=2, user_id=8)
    with factory() as session:
        save_document_chunks(
            session,
            document_id=1,
            user_id=7,
            chunks=[make_chunk(0, "owner content", 0)],
        )
        save_document_chunks(
            session,
            document_id=2,
            user_id=8,
            chunks=[make_chunk(0, "other content", 0)],
        )
        session.commit()

    with factory() as session:
        owned = get_document_chunks(session, document_id=1, user_id=7)
        hidden = get_document_chunks(session, document_id=2, user_id=7)
        hidden_count = count_document_chunks(
            session,
            document_id=2,
            user_id=7,
        )

    assert [chunk.content for chunk in owned] == ["owner content"]
    assert hidden == []
    assert hidden_count == 0


def test_user_cannot_save_chunks_for_another_users_document(
    chunk_database: tuple[sessionmaker[Session], object],
) -> None:
    factory, _ = chunk_database
    add_document(factory, document_id=2, user_id=8)

    with factory() as session, pytest.raises(
        DocumentChunkDocumentNotFoundError
    ):
        save_document_chunks(
            session,
            document_id=2,
            user_id=7,
            chunks=[make_chunk(0, "unauthorized content", 0)],
        )

    with factory() as session:
        assert count_document_chunks(session, document_id=2, user_id=8) == 0


def test_nonexistent_document_reads_are_indistinguishable_from_unowned_reads(
    chunk_database: tuple[sessionmaker[Session], object],
) -> None:
    factory, _ = chunk_database
    add_document(factory, document_id=2, user_id=8)

    with factory() as session:
        assert get_document_chunks(session, document_id=999, user_id=7) == []
        assert count_document_chunks(session, document_id=999, user_id=7) == 0
        assert get_document_chunks(session, document_id=2, user_id=7) == []
        assert count_document_chunks(session, document_id=2, user_id=7) == 0


def test_unicode_offsets_and_page_number_are_preserved(
    chunk_database: tuple[sessionmaker[Session], object],
) -> None:
    factory, _ = chunk_database
    add_document(factory)
    value = "Trí tuệ nhân tạo"

    with factory() as session:
        save_document_chunks(
            session,
            document_id=1,
            user_id=7,
            chunks=[make_chunk(0, value, 12, page_number=2)],
        )
        session.commit()
    with factory() as session:
        stored = get_document_chunks(session, document_id=1, user_id=7)[0]

    assert stored.content == value
    assert stored.start_char == 12
    assert stored.end_char == 12 + len(value)
    assert stored.character_count == len(value)
    assert stored.page_number == 2


def test_repository_rejects_empty_chunk_list(
    chunk_database: tuple[sessionmaker[Session], object],
) -> None:
    factory, _ = chunk_database
    add_document(factory)

    with factory() as session, pytest.raises(InvalidDocumentChunkError):
        save_document_chunks(session, document_id=1, user_id=7, chunks=[])


def test_repository_rejects_nonexistent_document(
    chunk_database: tuple[sessionmaker[Session], object],
) -> None:
    factory, _ = chunk_database

    with factory() as session, pytest.raises(
        DocumentChunkDocumentNotFoundError
    ):
        save_document_chunks(
            session,
            document_id=999,
            user_id=7,
            chunks=[make_chunk(0, "content", 0)],
        )


def test_repository_prevents_duplicate_document_chunks(
    chunk_database: tuple[sessionmaker[Session], object],
) -> None:
    factory, _ = chunk_database
    add_document(factory)
    chunks = [make_chunk(0, "content", 0)]
    with factory() as session:
        save_document_chunks(session, document_id=1, user_id=7, chunks=chunks)
        session.commit()

    with factory() as session, pytest.raises(DuplicateDocumentChunksError):
        save_document_chunks(session, document_id=1, user_id=7, chunks=chunks)


def test_database_unique_constraint_rejects_duplicate_index(
    chunk_database: tuple[sessionmaker[Session], object],
) -> None:
    factory, _ = chunk_database
    add_document(factory)
    now = datetime.now(timezone.utc)
    with factory() as session:
        session.add_all(
            [
                DocumentChunk(
                    document_id=1,
                    chunk_index=0,
                    content="first",
                    start_char=0,
                    end_char=5,
                    character_count=5,
                    page_number=None,
                    created_at=now,
                ),
                DocumentChunk(
                    document_id=1,
                    chunk_index=0,
                    content="duplicate",
                    start_char=5,
                    end_char=14,
                    character_count=9,
                    page_number=None,
                    created_at=now,
                ),
            ]
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

    with factory() as session:
        assert count_document_chunks(session, document_id=1, user_id=7) == 0


def test_foreign_key_rejects_unknown_document(
    chunk_database: tuple[sessionmaker[Session], object],
) -> None:
    factory, _ = chunk_database
    with factory() as session:
        session.add(
            DocumentChunk(
                document_id=999,
                chunk_index=0,
                content="orphan",
                start_char=0,
                end_char=6,
                character_count=6,
                page_number=None,
                created_at=datetime.now(timezone.utc),
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_database_cascade_delete_removes_document_chunks(
    chunk_database: tuple[sessionmaker[Session], object],
) -> None:
    factory, _ = chunk_database
    add_document(factory)
    with factory() as session:
        save_document_chunks(
            session,
            document_id=1,
            user_id=7,
            chunks=[make_chunk(0, "content", 0)],
        )
        session.commit()
        session.execute(delete(Document).where(Document.id == 1))
        session.commit()

    with factory() as session:
        assert count_document_chunks(session, document_id=1, user_id=7) == 0


@pytest.mark.parametrize(
    "overrides",
    [
        {"chunk_index": -1},
        {"start_char": -1, "end_char": 5, "character_count": 6},
        {"start_char": 5, "end_char": 5, "character_count": 0},
        {"start_char": 0, "end_char": 5, "character_count": 4},
        {"page_number": 0},
        {"content": "", "start_char": 0, "end_char": 1, "character_count": 1},
    ],
    ids=(
        "negative-index",
        "negative-start",
        "invalid-end",
        "invalid-count",
        "invalid-page",
        "empty-content",
    ),
)
def test_database_check_constraints(
    chunk_database: tuple[sessionmaker[Session], object],
    overrides: dict[str, object],
) -> None:
    factory, _ = chunk_database
    add_document(factory)
    values: dict[str, object] = {
        "document_id": 1,
        "chunk_index": 0,
        "content": "valid",
        "start_char": 0,
        "end_char": 5,
        "character_count": 5,
        "page_number": None,
        "created_at": datetime.now(timezone.utc),
    }
    values.update(overrides)

    with factory() as session:
        session.add(DocumentChunk(**values))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_repository_does_not_commit_implicitly(
    chunk_database: tuple[sessionmaker[Session], object],
) -> None:
    factory, _ = chunk_database
    add_document(factory)
    with factory() as session:
        save_document_chunks(
            session,
            document_id=1,
            user_id=7,
            chunks=[make_chunk(0, "content", 0)],
        )
        assert session.in_transaction() is True
        session.rollback()

    with factory() as session:
        assert count_document_chunks(session, document_id=1, user_id=7) == 0


def test_rollback_removes_all_chunks_after_insert_error(
    chunk_database: tuple[sessionmaker[Session], object],
) -> None:
    factory, database_engine = chunk_database
    add_document(factory)

    @event.listens_for(database_engine, "after_cursor_execute")
    def fail_after_chunk_insert(
        connection: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        if statement.lstrip().upper().startswith("INSERT INTO DOCUMENT_CHUNKS"):
            raise SQLAlchemyError("test-only insert failure")

    with factory() as session:
        with pytest.raises(DocumentChunkPersistenceError):
            save_document_chunks(
                session,
                document_id=1,
                user_id=7,
                chunks=[
                    make_chunk(0, "first", 0),
                    make_chunk(1, "second", 5),
                ],
            )
        session.rollback()
    event.remove(database_engine, "after_cursor_execute", fail_after_chunk_insert)

    with factory() as session:
        assert count_document_chunks(session, document_id=1, user_id=7) == 0


def test_saving_chunks_never_changes_another_document(
    chunk_database: tuple[sessionmaker[Session], object],
) -> None:
    factory, _ = chunk_database
    add_document(factory, document_id=1)
    add_document(factory, document_id=2)
    with factory() as session:
        save_document_chunks(
            session,
            document_id=1,
            user_id=7,
            chunks=[make_chunk(0, "first document", 0)],
        )
        session.commit()

    with factory() as session:
        assert count_document_chunks(session, document_id=1, user_id=7) == 1
        assert count_document_chunks(session, document_id=2, user_id=7) == 0
