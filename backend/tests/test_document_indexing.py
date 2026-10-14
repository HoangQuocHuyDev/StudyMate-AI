"""Tests for owner-scoped, recoverable document vector indexing."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import datetime, timezone
import logging
from pathlib import Path
from typing import Callable

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
    event,
    select,
)
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.document import Document
from app.models.document_deletion_job import DocumentDeletionJob
from app.models.document_chunk import DocumentChunk
from app.models.user import User
from app.services.rag.chroma_vector_store import (
    ChromaOpenError,
    ChunkVectorRecord,
    IncompatibleChromaCollectionError,
)
from app.services.rag.document_indexing import (
    DocumentIndexingFailedError,
    DocumentIndexingNotFoundError,
    DocumentNotIndexableError,
    index_document,
)
from app.services.rag.embedding_service import (
    GeminiEmbeddingRequestError,
    InvalidEmbeddingResponseError,
)


DIMENSIONS = 768


@pytest.fixture
def indexing_database(
    tmp_path: Path,
) -> Iterator[sessionmaker[Session]]:
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
    yield factory
    database_engine.dispose()


class FakeEmbedder:
    def __init__(
        self,
        *,
        error: Exception | None = None,
        callback: Callable[[], None] | None = None,
    ) -> None:
        self.error = error
        self.callback = callback
        self.calls: list[list[str]] = []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        if self.callback is not None:
            callback, self.callback = self.callback, None
            callback()
        if self.error is not None:
            raise self.error
        return [
            [float(len(self.calls) * 100 + index)] + [0.0] * (DIMENSIONS - 1)
            for index, _ in enumerate(texts)
        ]

    def embed_query(self, query: str) -> list[float]:
        raise AssertionError("Document indexing must not embed a query.")


class FakeVectorStore:
    def __init__(self) -> None:
        self.records: dict[str, ChunkVectorRecord] = {}
        self.upsert_calls: list[list[ChunkVectorRecord]] = []
        self.fail_on_upsert_call: int | None = None
        self.forced_ids: set[str] | None = None
        self.on_get_ids: Callable[[], None] | None = None

    def upsert_chunks(self, records: Sequence[ChunkVectorRecord]) -> int:
        values = list(records)
        self.upsert_calls.append(values)
        if self.fail_on_upsert_call == len(self.upsert_calls):
            raise RuntimeError("test-only vector failure")
        for record in values:
            self.records[record.id] = record
        return len(values)

    def get_document_vector_ids(
        self,
        *,
        user_id: int,
        document_id: int,
    ) -> set[str]:
        if self.on_get_ids is not None:
            self.on_get_ids()
        if self.forced_ids is not None:
            return set(self.forced_ids)
        return {
            vector_id
            for vector_id, record in self.records.items()
            if record.metadata["user_id"] == user_id
            and record.metadata["document_id"] == document_id
        }


def add_document(
    factory: sessionmaker[Session],
    *,
    document_id: int = 1,
    user_id: int = 7,
    status: str = "READY",
    rag_status: str = "PENDING",
    chunk_contents: tuple[str, ...] = ("Chunk zero", "Chunk one", "Chunk two"),
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
                storage_key=f"users/{user_id}/test-document-{document_id}",
                file_type="DOCX",
                mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                file_size=100,
                status=status,
                rag_status=rag_status,
                created_at=now,
                updated_at=now,
            )
        )
        session.flush()
        offset = 0
        for index, content in enumerate(chunk_contents):
            session.add(
                DocumentChunk(
                    id=document_id * 100 + index + 1,
                    document_id=document_id,
                    chunk_index=index,
                    content=content,
                    start_char=offset,
                    end_char=offset + len(content),
                    character_count=len(content),
                    page_number=index + 1 if index < 2 else None,
                    created_at=now,
                )
            )
            offset += len(content)
        session.commit()


def get_document(
    factory: sessionmaker[Session],
    document_id: int = 1,
) -> Document:
    with factory() as session:
        document = session.get(Document, document_id)
        assert document is not None
        session.expunge(document)
        return document


def get_chunk_snapshot(
    factory: sessionmaker[Session],
    document_id: int = 1,
) -> list[tuple[int, str]]:
    with factory() as session:
        return list(
            session.execute(
                select(DocumentChunk.chunk_index, DocumentChunk.content)
                .where(DocumentChunk.document_id == document_id)
                .order_by(DocumentChunk.chunk_index)
            ).all()
        )


def test_pending_document_is_indexed_successfully(
    indexing_database: sessionmaker[Session],
) -> None:
    add_document(indexing_database)
    embedder = FakeEmbedder()
    vector_store = FakeVectorStore()

    with indexing_database() as session:
        result = index_document(
            session,
            embedder,
            vector_store,
            document_id=1,
            user_id=7,
            batch_size=2,
        )

    document = get_document(indexing_database)
    assert result.rag_status == "READY"
    assert result.vector_count == 3
    assert result.indexed_at is not None
    assert document.rag_status == "READY"
    assert document.indexed_at is not None
    assert set(vector_store.records) == {
        "document_chunk:101",
        "document_chunk:102",
        "document_chunk:103",
    }


def test_failed_document_can_be_retried(
    indexing_database: sessionmaker[Session],
) -> None:
    add_document(indexing_database, rag_status="FAILED")

    with indexing_database() as session:
        result = index_document(
            session,
            FakeEmbedder(),
            FakeVectorStore(),
            document_id=1,
            user_id=7,
        )

    assert result.rag_status == "READY"


def test_other_users_document_is_indistinguishable_from_missing(
    indexing_database: sessionmaker[Session],
) -> None:
    add_document(indexing_database, user_id=7)

    with indexing_database() as session, pytest.raises(
        DocumentIndexingNotFoundError
    ):
        index_document(
            session,
            FakeEmbedder(),
            FakeVectorStore(),
            document_id=1,
            user_id=8,
        )


@pytest.mark.parametrize("status", ["UPLOADED", "PROCESSING"])
def test_unprocessed_document_is_rejected(
    indexing_database: sessionmaker[Session],
    status: str,
) -> None:
    add_document(indexing_database, status=status)

    with indexing_database() as session, pytest.raises(DocumentNotIndexableError):
        index_document(
            session,
            FakeEmbedder(),
            FakeVectorStore(),
            document_id=1,
            user_id=7,
        )


def test_already_indexed_document_is_rejected(
    indexing_database: sessionmaker[Session],
) -> None:
    add_document(indexing_database, rag_status="READY")

    with indexing_database() as session, pytest.raises(DocumentNotIndexableError):
        index_document(
            session,
            FakeEmbedder(),
            FakeVectorStore(),
            document_id=1,
            user_id=7,
        )


def test_document_without_chunks_is_rejected_without_embedding(
    indexing_database: sessionmaker[Session],
) -> None:
    add_document(indexing_database, chunk_contents=())
    embedder = FakeEmbedder()

    with indexing_database() as session, pytest.raises(DocumentNotIndexableError):
        index_document(
            session,
            embedder,
            FakeVectorStore(),
            document_id=1,
            user_id=7,
        )
    assert embedder.calls == []


def test_overlapping_request_cannot_claim_an_indexing_document(
    indexing_database: sessionmaker[Session],
) -> None:
    add_document(indexing_database)
    vector_store = FakeVectorStore()
    competing_errors: list[Exception] = []

    def competing_request() -> None:
        try:
            with indexing_database() as competing_session:
                index_document(
                    competing_session,
                    FakeEmbedder(),
                    vector_store,
                    document_id=1,
                    user_id=7,
                )
        except Exception as exc:
            competing_errors.append(exc)

    with indexing_database() as session:
        result = index_document(
            session,
            FakeEmbedder(callback=competing_request),
            vector_store,
            document_id=1,
            user_id=7,
        )

    assert result.rag_status == "READY"
    assert len(competing_errors) == 1
    assert isinstance(competing_errors[0], DocumentNotIndexableError)


def test_batching_preserves_chunk_order_and_metadata(
    indexing_database: sessionmaker[Session],
) -> None:
    contents = tuple(f"Chunk {index}" for index in range(5))
    add_document(indexing_database, chunk_contents=contents)
    embedder = FakeEmbedder()
    vector_store = FakeVectorStore()

    with indexing_database() as session:
        index_document(
            session,
            embedder,
            vector_store,
            document_id=1,
            user_id=7,
            batch_size=2,
        )

    assert embedder.calls == [list(contents[:2]), list(contents[2:4]), [contents[4]]]
    flattened = [record for call in vector_store.upsert_calls for record in call]
    assert [record.content for record in flattened] == list(contents)
    assert [record.metadata["chunk_index"] for record in flattened] == list(
        range(5)
    )
    assert "page_number" in flattened[0].metadata
    assert "page_number" not in flattened[-1].metadata


def test_whitespace_only_persisted_chunks_are_not_embedded(
    indexing_database: sessionmaker[Session],
) -> None:
    contents = ("Meaningful first chunk", "\n\n", "Meaningful final chunk")
    add_document(indexing_database, chunk_contents=contents)
    embedder = FakeEmbedder()
    vector_store = FakeVectorStore()

    with indexing_database() as session:
        result = index_document(
            session,
            embedder,
            vector_store,
            document_id=1,
            user_id=7,
        )

    assert result.rag_status == "READY"
    assert result.vector_count == 2
    assert embedder.calls == [[contents[0], contents[2]]]
    assert set(vector_store.records) == {
        "document_chunk:101",
        "document_chunk:103",
    }
    assert get_chunk_snapshot(indexing_database) == list(enumerate(contents))


def test_embedding_failure_marks_document_failed(
    indexing_database: sessionmaker[Session],
) -> None:
    add_document(indexing_database)

    with indexing_database() as session, pytest.raises(
        DocumentIndexingFailedError
    ):
        index_document(
            session,
            FakeEmbedder(error=TimeoutError("test-only timeout")),
            FakeVectorStore(),
            document_id=1,
            user_id=7,
        )

    document = get_document(indexing_database)
    assert document.rag_status == "FAILED"
    assert document.indexed_at is None


def test_vector_store_failure_marks_document_failed(
    indexing_database: sessionmaker[Session],
) -> None:
    add_document(indexing_database)
    vector_store = FakeVectorStore()
    vector_store.fail_on_upsert_call = 1

    with indexing_database() as session, pytest.raises(
        DocumentIndexingFailedError
    ):
        index_document(
            session,
            FakeEmbedder(),
            vector_store,
            document_id=1,
            user_id=7,
        )

    assert get_document(indexing_database).rag_status == "FAILED"


def test_retry_after_partial_upsert_is_idempotent(
    indexing_database: sessionmaker[Session],
) -> None:
    add_document(indexing_database)
    vector_store = FakeVectorStore()
    vector_store.fail_on_upsert_call = 2

    with indexing_database() as session, pytest.raises(
        DocumentIndexingFailedError
    ):
        index_document(
            session,
            FakeEmbedder(),
            vector_store,
            document_id=1,
            user_id=7,
            batch_size=2,
        )
    assert len(vector_store.records) == 2

    vector_store.fail_on_upsert_call = None
    vector_store.upsert_calls.clear()
    with indexing_database() as session:
        result = index_document(
            session,
            FakeEmbedder(),
            vector_store,
            document_id=1,
            user_id=7,
            batch_size=2,
        )

    assert result.vector_count == 3
    assert len(vector_store.records) == 3


@pytest.mark.parametrize("mode", ["missing", "extra"])
def test_exact_vector_id_verification_detects_mismatch(
    indexing_database: sessionmaker[Session],
    mode: str,
) -> None:
    add_document(indexing_database)
    vector_store = FakeVectorStore()
    expected = {
        "document_chunk:101",
        "document_chunk:102",
        "document_chunk:103",
    }
    vector_store.forced_ids = (
        expected - {"document_chunk:103"}
        if mode == "missing"
        else expected | {"document_chunk:999"}
    )

    with indexing_database() as session, pytest.raises(
        DocumentIndexingFailedError
    ):
        index_document(
            session,
            FakeEmbedder(),
            vector_store,
            document_id=1,
            user_id=7,
        )

    document = get_document(indexing_database)
    assert document.rag_status == "FAILED"
    assert document.indexed_at is None


def test_indexed_at_is_written_only_after_exact_verification(
    indexing_database: sessionmaker[Session],
) -> None:
    add_document(indexing_database)
    vector_store = FakeVectorStore()
    observed_states: list[tuple[str, object]] = []

    def observe_before_verification_returns() -> None:
        document = get_document(indexing_database)
        observed_states.append((document.rag_status, document.indexed_at))

    vector_store.on_get_ids = observe_before_verification_returns
    with indexing_database() as session:
        index_document(
            session,
            FakeEmbedder(),
            vector_store,
            document_id=1,
            user_id=7,
        )

    assert observed_states == [("INDEXING", None)]
    document = get_document(indexing_database)
    assert document.rag_status == "READY"
    assert document.indexed_at is not None


def test_indexing_never_changes_processing_status_or_chunks(
    indexing_database: sessionmaker[Session],
) -> None:
    add_document(indexing_database)
    original_chunks = get_chunk_snapshot(indexing_database)

    with indexing_database() as session:
        index_document(
            session,
            FakeEmbedder(),
            FakeVectorStore(),
            document_id=1,
            user_id=7,
        )

    assert get_document(indexing_database).status == "READY"
    assert get_chunk_snapshot(indexing_database) == original_chunks


def test_sensitive_provider_error_is_not_exposed(
    indexing_database: sessionmaker[Session],
) -> None:
    add_document(indexing_database)
    secret = "test-only-api-key-must-not-leak"

    with indexing_database() as session, pytest.raises(
        DocumentIndexingFailedError
    ) as captured:
        index_document(
            session,
            FakeEmbedder(error=RuntimeError(f"bad API key: {secret}")),
            FakeVectorStore(),
            document_id=1,
            user_id=7,
        )

    assert secret not in str(captured.value)
    assert secret not in repr(captured.value)


@pytest.mark.parametrize("batch_size", [0, -1, 101, 1.5, True])
def test_invalid_batch_size_is_rejected_before_claim(
    indexing_database: sessionmaker[Session],
    batch_size: object,
) -> None:
    add_document(indexing_database)

    with indexing_database() as session, pytest.raises(ValueError):
        index_document(
            session,
            FakeEmbedder(),
            FakeVectorStore(),
            document_id=1,
            user_id=7,
            batch_size=batch_size,
        )

    assert get_document(indexing_database).rag_status == "PENDING"


@pytest.mark.parametrize(
    ("provider_error", "error_code", "provider_http_status"),
    [
        (
            GeminiEmbeddingRequestError(
                "safe",
                error_code="gemini_timeout",
                failure_phase="sdk_call",
                exception_type="ReadTimeout",
                elapsed_ms=12.5,
            ),
            "gemini_timeout",
            None,
        ),
        (
            GeminiEmbeddingRequestError(
                "safe",
                error_code="gemini_rate_limit",
                provider_http_status=429,
            ),
            "gemini_rate_limit",
            429,
        ),
        (
            GeminiEmbeddingRequestError(
                "safe",
                error_code="gemini_auth_or_permission",
                provider_http_status=403,
            ),
            "gemini_auth_or_permission",
            403,
        ),
        (
            InvalidEmbeddingResponseError("safe"),
            "gemini_invalid_response",
            None,
        ),
    ],
)
def test_embedding_failures_are_logged_with_safe_categories(
    indexing_database: sessionmaker[Session],
    caplog: pytest.LogCaptureFixture,
    provider_error: Exception,
    error_code: str,
    provider_http_status: int | None,
) -> None:
    add_document(indexing_database)

    with caplog.at_level(
        logging.INFO,
        logger="app.services.rag.document_indexing",
    ):
        with indexing_database() as session, pytest.raises(
            DocumentIndexingFailedError
        ):
            index_document(
                session,
                FakeEmbedder(error=provider_error),
                FakeVectorStore(),
                document_id=1,
                user_id=7,
            )

    failure = next(
        record
        for record in caplog.records
        if getattr(record, "event", None) == "document_indexing_stage_failed"
    )
    final = next(
        record
        for record in caplog.records
        if getattr(record, "event", None) == "document_indexing_failed"
    )
    assert failure.stage == "embedding_batch"
    assert failure.batch_index == 1
    assert failure.total_batches == 1
    assert failure.chunk_count == 3
    assert failure.error_code == error_code
    assert failure.provider_http_status == provider_http_status
    assert isinstance(failure.elapsed_ms, float)
    assert failure.failure_phase == provider_error.failure_phase
    assert failure.exception_type == provider_error.exception_type
    if provider_error.elapsed_ms is not None:
        assert failure.elapsed_ms == provider_error.elapsed_ms
    assert final.stage == "indexing_failed"
    assert final.error_code == error_code
    assert final.failure_phase == provider_error.failure_phase
    assert final.exception_type == provider_error.exception_type
    assert get_document(indexing_database).rag_status == "FAILED"


@pytest.mark.parametrize(
    ("error", "error_code"),
    [
        (RuntimeError("private chroma error"), "chroma_upsert_failed"),
        (ChromaOpenError("private path"), "chroma_open_failed"),
        (
            IncompatibleChromaCollectionError("private collection detail"),
            "chroma_incompatible_collection",
        ),
    ],
)
def test_chroma_upsert_failures_are_logged_with_safe_categories(
    indexing_database: sessionmaker[Session],
    caplog: pytest.LogCaptureFixture,
    error: Exception,
    error_code: str,
) -> None:
    add_document(indexing_database)

    class FailingVectorStore(FakeVectorStore):
        def upsert_chunks(
            self,
            records: Sequence[ChunkVectorRecord],
        ) -> int:
            raise error

    with caplog.at_level(
        logging.INFO,
        logger="app.services.rag.document_indexing",
    ):
        with indexing_database() as session, pytest.raises(
            DocumentIndexingFailedError
        ):
            index_document(
                session,
                FakeEmbedder(),
                FailingVectorStore(),
                document_id=1,
                user_id=7,
            )

    failure = next(
        record
        for record in caplog.records
        if getattr(record, "event", None) == "document_indexing_stage_failed"
    )
    assert failure.stage == "chroma_upsert_batch"
    assert failure.error_code == error_code
    assert failure.provider_http_status is None
    assert get_document(indexing_database).rag_status == "FAILED"


def test_chroma_verification_failure_is_logged(
    indexing_database: sessionmaker[Session],
    caplog: pytest.LogCaptureFixture,
) -> None:
    add_document(indexing_database)
    vector_store = FakeVectorStore()

    def fail_verification() -> None:
        raise RuntimeError("private verification detail")

    vector_store.on_get_ids = fail_verification
    with caplog.at_level(
        logging.INFO,
        logger="app.services.rag.document_indexing",
    ):
        with indexing_database() as session, pytest.raises(
            DocumentIndexingFailedError
        ):
            index_document(
                session,
                FakeEmbedder(),
                vector_store,
                document_id=1,
                user_id=7,
            )

    failure = next(
        record
        for record in caplog.records
        if getattr(record, "event", None) == "document_indexing_stage_failed"
    )
    assert failure.stage == "vector_verification"
    assert failure.error_code == "chroma_verify_failed"
    assert failure.batch_index is None
    assert get_document(indexing_database).rag_status == "FAILED"


def test_vector_id_mismatch_is_logged(
    indexing_database: sessionmaker[Session],
    caplog: pytest.LogCaptureFixture,
) -> None:
    add_document(indexing_database)
    vector_store = FakeVectorStore()
    vector_store.forced_ids = {"document_chunk:101"}

    with caplog.at_level(
        logging.INFO,
        logger="app.services.rag.document_indexing",
    ):
        with indexing_database() as session, pytest.raises(
            DocumentIndexingFailedError
        ):
            index_document(
                session,
                FakeEmbedder(),
                vector_store,
                document_id=1,
                user_id=7,
            )

    failure = next(
        record
        for record in caplog.records
        if getattr(record, "event", None) == "document_indexing_stage_failed"
    )
    assert failure.stage == "vector_verification"
    assert failure.error_code == "vector_id_mismatch"
    assert get_document(indexing_database).rag_status == "FAILED"


def test_second_batch_failure_logs_exact_batch_progress(
    indexing_database: sessionmaker[Session],
    caplog: pytest.LogCaptureFixture,
) -> None:
    contents = tuple(f"Nội dung an toàn {index}" for index in range(48))
    add_document(indexing_database, chunk_contents=contents)
    vector_store = FakeVectorStore()
    vector_store.fail_on_upsert_call = 2

    with caplog.at_level(
        logging.INFO,
        logger="app.services.rag.document_indexing",
    ):
        with indexing_database() as session, pytest.raises(
            DocumentIndexingFailedError
        ):
            index_document(
                session,
                FakeEmbedder(),
                vector_store,
                document_id=1,
                user_id=7,
            )

    failure = next(
        record
        for record in caplog.records
        if getattr(record, "event", None) == "document_indexing_stage_failed"
    )
    assert failure.stage == "chroma_upsert_batch"
    assert failure.batch_index == 2
    assert failure.total_batches == 2
    assert failure.chunk_count == 48
    assert failure.batch_chunk_count == 16


def test_diagnostic_logs_never_include_chunk_content_or_provider_secrets(
    indexing_database: sessionmaker[Session],
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret_chunk = "SECRET_CHUNK_CONTENT_AND_API_KEY"
    secret_error = "SECRET_PROVIDER_EXCEPTION_DETAIL"
    add_document(indexing_database, chunk_contents=(secret_chunk,))

    with caplog.at_level(
        logging.INFO,
        logger="app.services.rag.document_indexing",
    ):
        with indexing_database() as session, pytest.raises(
            DocumentIndexingFailedError
        ):
            index_document(
                session,
                FakeEmbedder(
                    error=GeminiEmbeddingRequestError(
                        secret_error,
                        error_code="gemini_request_failed",
                    )
                ),
                FakeVectorStore(),
                document_id=1,
                user_id=7,
            )

    serialized_logs = " ".join(
        f"{record.getMessage()} {record.__dict__}"
        for record in caplog.records
        if record.name == "app.services.rag.document_indexing"
    )
    assert secret_chunk not in serialized_logs
    assert secret_error not in serialized_logs
    assert "Traceback" not in serialized_logs
