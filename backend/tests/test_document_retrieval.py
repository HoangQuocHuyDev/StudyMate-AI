"""Tests for owner-scoped semantic chunk retrieval and verification."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import datetime, timezone
from pathlib import Path

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
)
from sqlalchemy.orm import Session, sessionmaker

from app.models.document import Document
from app.models.document_deletion_job import DocumentDeletionJob
from app.models.document_chunk import DocumentChunk
from app.models.user import User
from app.core.config import _load_rag_max_cosine_distance
from app.services.rag.chroma_vector_store import ChunkQueryResult
from app.services.rag.document_retrieval import (
    MAX_QUERY_LENGTH,
    DocumentNotRetrievableError,
    DocumentRetrievalConsistencyError,
    DocumentRetrievalNotFoundError,
    DocumentRetrievalProviderError,
    DocumentQueryEmbeddingError,
    DocumentRetrievalDeadlineExceededError,
    DocumentVectorSearchError,
    InvalidDocumentRetrievalRequestError,
    retrieve_document_chunks,
)


DIMENSIONS = 768


@pytest.fixture
def retrieval_database(
    tmp_path: Path,
) -> Iterator[sessionmaker[Session]]:
    database_engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'retrieval.sqlite3'}",
        connect_args={"check_same_thread": False},
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
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.queries: list[str] = []
        self.timeouts: list[float | None] = []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise AssertionError("Retrieval must not embed documents.")

    def embed_query(
        self,
        query: str,
        *,
        timeout_seconds: float | None = None,
    ) -> list[float]:
        self.queries.append(query)
        self.timeouts.append(timeout_seconds)
        if self.error is not None:
            raise self.error
        return [0.25] * DIMENSIONS


class FakeVectorStore:
    def __init__(
        self,
        results: Sequence[ChunkQueryResult] = (),
        *,
        error: Exception | None = None,
    ) -> None:
        self.results = list(results)
        self.error = error
        self.calls: list[dict[str, object]] = []

    def query_chunks(
        self,
        query_embedding: Sequence[float],
        *,
        user_id: int,
        document_id: int,
        limit: int,
    ) -> list[ChunkQueryResult]:
        self.calls.append(
            {
                "query_embedding": query_embedding,
                "user_id": user_id,
                "document_id": document_id,
                "limit": limit,
            }
        )
        if self.error is not None:
            raise self.error
        return list(self.results)


def add_document(
    factory: sessionmaker[Session],
    *,
    document_id: int = 1,
    user_id: int = 7,
    status: str = "READY",
    rag_status: str = "READY",
    contents: tuple[str, ...] = (
        "Nội dung PostgreSQL thứ nhất",
        "Nội dung PostgreSQL thứ hai",
        "Nội dung PostgreSQL thứ ba",
    ),
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
                storage_key=f"users/{user_id}/document-{document_id}",
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
        for index, content in enumerate(contents):
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


def vector_result(
    *,
    document_id: int = 1,
    user_id: int = 7,
    chunk_index: int = 0,
    distance: float = 0.1,
    content: str = "untrusted Chroma content",
    metadata_overrides: dict[str, int] | None = None,
    vector_id: str | None = None,
) -> ChunkQueryResult:
    chunk_id = document_id * 100 + chunk_index + 1
    metadata = {
        "user_id": user_id,
        "document_id": document_id,
        "chunk_id": chunk_id,
        "chunk_index": chunk_index,
    }
    if chunk_index < 2:
        metadata["page_number"] = chunk_index + 1
    if metadata_overrides:
        metadata.update(metadata_overrides)
    return ChunkQueryResult(
        id=vector_id or f"document_chunk:{chunk_id}",
        content=content,
        metadata=metadata,
        distance=distance,
    )


def retrieve(
    factory: sessionmaker[Session],
    embedder: FakeEmbedder,
    vector_store: FakeVectorStore,
    **kwargs: object,
):
    with factory() as session:
        return retrieve_document_chunks(
            session,
            embedder,
            vector_store,
            document_id=kwargs.pop("document_id", 1),
            user_id=kwargs.pop("user_id", 7),
            query=kwargs.pop("query", "  trí tuệ nhân tạo  "),
            top_k=kwargs.pop("top_k", 5),
            max_cosine_distance=kwargs.pop("max_cosine_distance", None),
            **kwargs,
        )


def test_retrieval_succeeds_with_owner_filters_and_validated_output(
    retrieval_database: sessionmaker[Session],
) -> None:
    add_document(retrieval_database)
    embedder = FakeEmbedder()
    vector_store = FakeVectorStore(
        [vector_result(chunk_index=1, distance=0.08)]
    )

    results = retrieve(
        retrieval_database,
        embedder,
        vector_store,
        top_k=3,
    )

    assert embedder.queries == ["trí tuệ nhân tạo"]
    assert vector_store.calls[0]["user_id"] == 7
    assert vector_store.calls[0]["document_id"] == 1
    assert vector_store.calls[0]["limit"] == 3
    assert results[0].chunk_id == 102
    assert results[0].document_id == 1
    assert results[0].chunk_index == 1
    assert results[0].page_number == 2
    assert results[0].distance == 0.08


@pytest.mark.parametrize("user_id", [8, 99])
def test_other_user_is_rejected_before_embedding(
    retrieval_database: sessionmaker[Session],
    user_id: int,
) -> None:
    add_document(retrieval_database, user_id=7)
    embedder = FakeEmbedder()
    vector_store = FakeVectorStore()

    with pytest.raises(DocumentRetrievalNotFoundError):
        retrieve(
            retrieval_database,
            embedder,
            vector_store,
            user_id=user_id,
        )

    assert embedder.queries == []
    assert vector_store.calls == []


def test_missing_document_is_rejected_before_embedding(
    retrieval_database: sessionmaker[Session],
) -> None:
    embedder = FakeEmbedder()

    with pytest.raises(DocumentRetrievalNotFoundError):
        retrieve(retrieval_database, embedder, FakeVectorStore())

    assert embedder.queries == []


@pytest.mark.parametrize(
    ("status", "rag_status", "contents"),
    [
        ("UPLOADED", "READY", ("Chunk",)),
        ("PROCESSING", "READY", ("Chunk",)),
        ("READY", "PENDING", ("Chunk",)),
        ("READY", "FAILED", ("Chunk",)),
        ("READY", "READY", ()),
    ],
)
def test_document_must_be_processed_indexed_and_have_chunks(
    retrieval_database: sessionmaker[Session],
    status: str,
    rag_status: str,
    contents: tuple[str, ...],
) -> None:
    add_document(
        retrieval_database,
        status=status,
        rag_status=rag_status,
        contents=contents,
    )
    embedder = FakeEmbedder()

    with pytest.raises(DocumentNotRetrievableError):
        retrieve(retrieval_database, embedder, FakeVectorStore())

    assert embedder.queries == []


@pytest.mark.parametrize("query", ["", "   ", None, 42])
def test_empty_or_nonstring_query_is_rejected(
    retrieval_database: sessionmaker[Session],
    query: object,
) -> None:
    with pytest.raises(InvalidDocumentRetrievalRequestError):
        retrieve(
            retrieval_database,
            FakeEmbedder(),
            FakeVectorStore(),
            query=query,
        )


def test_overlong_query_is_rejected(
    retrieval_database: sessionmaker[Session],
) -> None:
    with pytest.raises(InvalidDocumentRetrievalRequestError):
        retrieve(
            retrieval_database,
            FakeEmbedder(),
            FakeVectorStore(),
            query=f" {'a' * (MAX_QUERY_LENGTH + 1)} ",
        )


@pytest.mark.parametrize("top_k", [0, 21, -1, 1.5, True, "5"])
def test_invalid_top_k_is_rejected(
    retrieval_database: sessionmaker[Session],
    top_k: object,
) -> None:
    with pytest.raises(InvalidDocumentRetrievalRequestError):
        retrieve(
            retrieval_database,
            FakeEmbedder(),
            FakeVectorStore(),
            top_k=top_k,
        )


@pytest.mark.parametrize(
    ("document_id", "user_id"),
    [(0, 7), (-1, 7), (1.5, 7), (True, 7), (1, 0), (1, "7")],
)
def test_invalid_identifiers_are_rejected(
    retrieval_database: sessionmaker[Session],
    document_id: object,
    user_id: object,
) -> None:
    with pytest.raises(InvalidDocumentRetrievalRequestError):
        retrieve(
            retrieval_database,
            FakeEmbedder(),
            FakeVectorStore(),
            document_id=document_id,
            user_id=user_id,
        )


def test_results_from_other_user_or_document_are_removed(
    retrieval_database: sessionmaker[Session],
) -> None:
    add_document(retrieval_database, document_id=1, user_id=7)
    add_document(retrieval_database, document_id=2, user_id=7)
    results = retrieve(
        retrieval_database,
        FakeEmbedder(),
        FakeVectorStore(
            [
                vector_result(chunk_index=0),
                vector_result(chunk_index=1, metadata_overrides={"user_id": 8}),
                vector_result(document_id=2, chunk_index=0),
            ]
        ),
    )

    assert [result.chunk_id for result in results] == [101]
    assert all(result.document_id == 1 for result in results)


def test_forged_metadata_and_missing_chunks_are_removed(
    retrieval_database: sessionmaker[Session],
) -> None:
    add_document(retrieval_database)
    missing = vector_result(
        vector_id="document_chunk:999",
        metadata_overrides={"chunk_id": 999, "chunk_index": 9},
    )
    results = retrieve(
        retrieval_database,
        FakeEmbedder(),
        FakeVectorStore(
            [
                vector_result(chunk_index=0),
                vector_result(chunk_index=1, metadata_overrides={"chunk_index": 99}),
                missing,
            ]
        ),
    )

    assert [result.chunk_id for result in results] == [101]


def test_content_always_comes_from_postgresql(
    retrieval_database: sessionmaker[Session],
) -> None:
    add_document(retrieval_database)

    result = retrieve(
        retrieval_database,
        FakeEmbedder(),
        FakeVectorStore(
            [vector_result(chunk_index=0, content="forged vector content")]
        ),
    )[0]

    assert result.content == "Nội dung PostgreSQL thứ nhất"
    assert "forged" not in result.content


def test_relevance_order_is_preserved_and_duplicates_are_removed(
    retrieval_database: sessionmaker[Session],
) -> None:
    add_document(retrieval_database)
    second = vector_result(chunk_index=1, distance=0.01)
    first = vector_result(chunk_index=0, distance=0.12)

    results = retrieve(
        retrieval_database,
        FakeEmbedder(),
        FakeVectorStore([second, second, first]),
    )

    assert [result.chunk_id for result in results] == [102, 101]
    assert [result.distance for result in results] == [0.01, 0.12]


def test_empty_vector_results_return_an_empty_list(
    retrieval_database: sessionmaker[Session],
) -> None:
    add_document(retrieval_database)

    assert retrieve(
        retrieval_database,
        FakeEmbedder(),
        FakeVectorStore(),
    ) == []


def test_disabled_threshold_preserves_all_verified_top_k_results(
    retrieval_database: sessionmaker[Session],
) -> None:
    add_document(retrieval_database)

    results = retrieve(
        retrieval_database,
        FakeEmbedder(),
        FakeVectorStore(
            [
                vector_result(chunk_index=0, distance=0.05),
                vector_result(chunk_index=1, distance=1.25),
            ]
        ),
        max_cosine_distance=None,
    )

    assert [item.chunk_id for item in results] == [101, 102]


def test_enabled_threshold_keeps_only_low_cosine_distances(
    retrieval_database: sessionmaker[Session],
) -> None:
    add_document(retrieval_database)

    results = retrieve(
        retrieval_database,
        FakeEmbedder(),
        FakeVectorStore(
            [
                vector_result(chunk_index=0, distance=0.2),
                vector_result(chunk_index=1, distance=0.8),
            ]
        ),
        max_cosine_distance=0.5,
    )

    assert [item.chunk_id for item in results] == [101]
    assert results[0].distance == pytest.approx(0.2)


def test_result_exactly_at_threshold_is_included(
    retrieval_database: sessionmaker[Session],
) -> None:
    add_document(retrieval_database)

    results = retrieve(
        retrieval_database,
        FakeEmbedder(),
        FakeVectorStore(
            [
                vector_result(chunk_index=0, distance=0.5),
                vector_result(chunk_index=1, distance=0.500001),
            ]
        ),
        max_cosine_distance=0.5,
    )

    assert [item.chunk_id for item in results] == [101]


def test_all_results_above_threshold_return_no_relevant_chunks(
    retrieval_database: sessionmaker[Session],
) -> None:
    add_document(retrieval_database)

    results = retrieve(
        retrieval_database,
        FakeEmbedder(),
        FakeVectorStore(
            [
                vector_result(chunk_index=0, distance=0.7),
                vector_result(chunk_index=1, distance=1.1),
            ]
        ),
        max_cosine_distance=0.5,
    )

    assert results == []


@pytest.mark.parametrize(
    "threshold",
    [-0.1, 2.1, float("nan"), float("inf"), True, "0.5"],
)
def test_invalid_threshold_is_rejected_before_embedding(
    retrieval_database: sessionmaker[Session],
    threshold: object,
) -> None:
    embedder = FakeEmbedder()

    with pytest.raises(InvalidDocumentRetrievalRequestError):
        retrieve(
            retrieval_database,
            embedder,
            FakeVectorStore(),
            max_cosine_distance=threshold,
        )

    assert embedder.queries == []


@pytest.mark.parametrize("disabled_value", [None, "off", "NONE", "disabled"])
def test_threshold_configuration_defaults_to_disabled(
    monkeypatch: pytest.MonkeyPatch,
    disabled_value: str | None,
) -> None:
    if disabled_value is None:
        monkeypatch.delenv("RAG_MAX_COSINE_DISTANCE", raising=False)
    else:
        monkeypatch.setenv("RAG_MAX_COSINE_DISTANCE", disabled_value)

    assert _load_rag_max_cosine_distance() is None


def test_threshold_configuration_accepts_calibrated_distance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RAG_MAX_COSINE_DISTANCE", "0.42")

    assert _load_rag_max_cosine_distance() == pytest.approx(0.42)


@pytest.mark.parametrize(
    "value",
    ["", "-0.01", "2.01", "nan", "infinity", "not-a-number"],
)
def test_threshold_configuration_rejects_invalid_values(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv("RAG_MAX_COSINE_DISTANCE", value)

    with pytest.raises(RuntimeError):
        _load_rag_max_cosine_distance()


def test_external_providers_are_called_without_an_open_database_transaction(
    retrieval_database: sessionmaker[Session],
) -> None:
    add_document(retrieval_database)
    with retrieval_database() as session:
        class TransactionCheckingEmbedder(FakeEmbedder):
            def embed_query(
                self,
                query: str,
                *,
                timeout_seconds: float | None = None,
            ) -> list[float]:
                assert not session.in_transaction()
                return super().embed_query(query)

        class TransactionCheckingVectorStore(FakeVectorStore):
            def query_chunks(
                self,
                query_embedding: Sequence[float],
                *,
                user_id: int,
                document_id: int,
                limit: int,
            ) -> list[ChunkQueryResult]:
                assert not session.in_transaction()
                return super().query_chunks(
                    query_embedding,
                    user_id=user_id,
                    document_id=document_id,
                    limit=limit,
                )

        results = retrieve_document_chunks(
            session,
            TransactionCheckingEmbedder(),
            TransactionCheckingVectorStore([vector_result()]),
            document_id=1,
            user_id=7,
            query="Câu hỏi",
        )

    assert [result.chunk_id for result in results] == [101]


def test_completely_invalid_results_raise_consistency_error(
    retrieval_database: sessionmaker[Session],
) -> None:
    add_document(retrieval_database)

    with pytest.raises(DocumentRetrievalConsistencyError):
        retrieve(
            retrieval_database,
            FakeEmbedder(),
            FakeVectorStore(
                [vector_result(metadata_overrides={"document_id": 999})]
            ),
        )


@pytest.mark.parametrize(
    ("provider", "expected_error"),
    [
        ("gemini", DocumentQueryEmbeddingError),
        ("chroma", DocumentVectorSearchError),
    ],
)
def test_provider_errors_are_safe_and_do_not_leak_sensitive_details(
    retrieval_database: sessionmaker[Session],
    provider: str,
    expected_error: type[DocumentRetrievalProviderError],
) -> None:
    add_document(retrieval_database)
    sensitive = "secret-api-key query-content internal-path"
    embedder = FakeEmbedder(
        error=RuntimeError(sensitive) if provider == "gemini" else None
    )
    vector_store = FakeVectorStore(
        error=RuntimeError(sensitive) if provider == "chroma" else None
    )

    with pytest.raises(expected_error) as captured:
        retrieve(retrieval_database, embedder, vector_store)

    assert sensitive not in str(captured.value)
    assert "secret" not in str(captured.value).lower()


class FakeDeadline:
    def __init__(self, remaining: float) -> None:
        self.remaining = remaining

    def remaining_seconds(self) -> float:
        if self.remaining <= 0:
            raise TimeoutError("expired-sensitive-detail")
        return self.remaining


def test_embedding_is_bounded_by_remaining_retrieval_deadline(
    retrieval_database: sessionmaker[Session],
) -> None:
    add_document(retrieval_database)
    embedder = FakeEmbedder()

    retrieve(
        retrieval_database,
        embedder,
        FakeVectorStore(),
        deadline=FakeDeadline(4.25),
    )

    assert embedder.timeouts == [pytest.approx(4.25)]


def test_deadline_expiring_during_embedding_stops_before_chroma(
    retrieval_database: sessionmaker[Session],
) -> None:
    add_document(retrieval_database)
    deadline = FakeDeadline(1)
    vector_store = FakeVectorStore()

    class ExpiringEmbedder(FakeEmbedder):
        def embed_query(
            self,
            query: str,
            *,
            timeout_seconds: float | None = None,
        ) -> list[float]:
            result = super().embed_query(
                query,
                timeout_seconds=timeout_seconds,
            )
            deadline.remaining = 0
            return result

    with pytest.raises(DocumentRetrievalDeadlineExceededError):
        retrieve(
            retrieval_database,
            ExpiringEmbedder(),
            vector_store,
            deadline=deadline,
        )

    assert vector_store.calls == []


def test_deadline_expiring_during_chroma_is_distinct_from_vector_error(
    retrieval_database: sessionmaker[Session],
) -> None:
    add_document(retrieval_database)
    deadline = FakeDeadline(1)

    class ExpiringVectorStore(FakeVectorStore):
        def query_chunks(self, *args: object, **kwargs: object):
            result = super().query_chunks(*args, **kwargs)
            deadline.remaining = 0
            return result

    with pytest.raises(DocumentRetrievalDeadlineExceededError):
        retrieve(
            retrieval_database,
            FakeEmbedder(),
            ExpiringVectorStore([vector_result()]),
            deadline=deadline,
        )
