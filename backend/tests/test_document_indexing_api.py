"""Isolated API tests for synchronous RAG document indexing."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import pytest
from fastapi.testclient import TestClient
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

import app.dependencies.rag as rag_dependencies
from app.core.config import get_settings
from app.core.security import create_access_token
from app.db.session import get_db
from app.dependencies.rag import (
    RagIndexingResources,
    get_rag_indexing_resources,
)
from app.main import app
from app.models.document import Document
from app.models.document_deletion_job import DocumentDeletionJob
from app.models.document_chunk import DocumentChunk
from app.models.user import User
from app.services.rag.chroma_vector_store import ChunkVectorRecord
from app.services.summary.concurrency import (
    SummaryConcurrencyError,
    SummaryConcurrencyLimitError,
)


DIMENSIONS = 768


def authorization_header(user_id: int) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id, 0)}"}


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
        return [[float(index)] * DIMENSIONS for index, _ in enumerate(texts)]

    def embed_query(self, query: str) -> list[float]:
        raise AssertionError("Indexing must not embed queries.")


class FakeVectorStore:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.records: dict[str, ChunkVectorRecord] = {}

    def upsert_chunks(self, records: Sequence[ChunkVectorRecord]) -> int:
        if self.error is not None:
            raise self.error
        values = list(records)
        for record in values:
            self.records[record.id] = record
        return len(values)

    def get_document_vector_ids(
        self,
        *,
        user_id: int,
        document_id: int,
    ) -> set[str]:
        return {
            vector_id
            for vector_id, record in self.records.items()
            if record.metadata["user_id"] == user_id
            and record.metadata["document_id"] == document_id
        }


class FakeCapacityCoordinator:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.active = 0
        self.entries = 0
        self.exits = 0

    @contextmanager
    def capacity(self, user_id: int) -> Iterator[None]:
        assert user_id > 0
        self.entries += 1
        if self.error is not None:
            raise self.error
        self.active += 1
        try:
            yield
        finally:
            self.active -= 1
            self.exits += 1


@pytest.fixture
def indexing_api_environment(
    client: TestClient,
    tmp_path: Path,
) -> Iterator[
    tuple[
        TestClient,
        sessionmaker[Session],
        FakeEmbedder,
        FakeVectorStore,
    ]
]:
    """Route API state and external services to isolated fakes."""

    database_engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'indexing-api.sqlite3'}",
        connect_args={"check_same_thread": False, "timeout": 5},
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
    embedder = FakeEmbedder()
    vector_store = FakeVectorStore()
    resources = RagIndexingResources(embedder, vector_store)

    def override_database() -> Iterator[Session]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_database
    app.dependency_overrides[get_rag_indexing_resources] = lambda: resources
    yield client, factory, embedder, vector_store
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_rag_indexing_resources, None)
    app.dependency_overrides.pop(get_settings, None)
    database_engine.dispose()


def add_user(factory: sessionmaker[Session], user_id: int) -> None:
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
                    created_at=datetime.now(timezone.utc),
                )
            )
            session.commit()


def add_document(
    factory: sessionmaker[Session],
    *,
    document_id: int = 1,
    user_id: int = 42,
    status: str = "READY",
    rag_status: str = "PENDING",
    chunks: tuple[str, ...] = ("Nội dung học tập", "Chunk thứ hai"),
) -> None:
    add_user(factory, user_id)
    now = datetime.now(timezone.utc)
    with factory() as session:
        session.add(
            Document(
                id=document_id,
                user_id=user_id,
                title="RAG API document",
                original_filename="rag-api.docx",
                storage_key=f"users/{user_id}/private-secret-key",
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
        for index, content in enumerate(chunks):
            session.add(
                DocumentChunk(
                    id=document_id * 100 + index + 1,
                    document_id=document_id,
                    chunk_index=index,
                    content=content,
                    start_char=offset,
                    end_char=offset + len(content),
                    character_count=len(content),
                    page_number=None,
                    created_at=now,
                )
            )
            offset += len(content)
        session.commit()


def stored_document(
    factory: sessionmaker[Session],
    document_id: int = 1,
) -> Document:
    with factory() as session:
        document = session.get(Document, document_id)
        assert document is not None
        session.expunge(document)
        return document


@pytest.mark.parametrize(
    ("method", "path"),
    [("post", "/documents/1/index"), ("get", "/documents/1/rag-status")],
)
def test_rag_endpoints_require_jwt(
    indexing_api_environment: tuple[
        TestClient, sessionmaker[Session], FakeEmbedder, FakeVectorStore
    ],
    method: str,
    path: str,
) -> None:
    client, _, _, _ = indexing_api_environment

    response = getattr(client, method)(path)

    assert response.status_code == 401


def test_other_user_cannot_index_or_view_rag_status(
    indexing_api_environment: tuple[
        TestClient, sessionmaker[Session], FakeEmbedder, FakeVectorStore
    ],
) -> None:
    client, factory, _, _ = indexing_api_environment
    add_document(factory, user_id=8)
    add_user(factory, 42)
    headers = authorization_header(42)

    assert client.post("/documents/1/index", headers=headers).status_code == 404
    assert (
        client.get("/documents/1/rag-status", headers=headers).status_code == 404
    )


@pytest.mark.parametrize("initial_rag_status", ["PENDING", "FAILED"])
def test_retryable_document_indexes_successfully(
    indexing_api_environment: tuple[
        TestClient, sessionmaker[Session], FakeEmbedder, FakeVectorStore
    ],
    initial_rag_status: str,
) -> None:
    client, factory, embedder, _ = indexing_api_environment
    add_document(factory, rag_status=initial_rag_status)

    response = client.post(
        "/documents/1/index",
        headers=authorization_header(42),
    )

    assert response.status_code == 200
    assert response.json()["document_id"] == 1
    assert response.json()["rag_status"] == "READY"
    assert response.json()["vector_count"] == 2
    assert response.json()["indexed_at"] is not None
    assert embedder.calls == [["Nội dung học tập", "Chunk thứ hai"]]


@pytest.mark.parametrize("rag_status", ["INDEXING", "READY"])
def test_non_retryable_rag_state_returns_conflict(
    indexing_api_environment: tuple[
        TestClient, sessionmaker[Session], FakeEmbedder, FakeVectorStore
    ],
    rag_status: str,
) -> None:
    client, factory, embedder, _ = indexing_api_environment
    add_document(factory, rag_status=rag_status)

    response = client.post(
        "/documents/1/index",
        headers=authorization_header(42),
    )

    assert response.status_code == 409
    assert embedder.calls == []


def test_unprocessed_document_returns_conflict(
    indexing_api_environment: tuple[
        TestClient, sessionmaker[Session], FakeEmbedder, FakeVectorStore
    ],
) -> None:
    client, factory, embedder, _ = indexing_api_environment
    add_document(factory, status="UPLOADED")

    response = client.post(
        "/documents/1/index",
        headers=authorization_header(42),
    )

    assert response.status_code == 409
    assert embedder.calls == []


def test_document_without_chunks_returns_conflict(
    indexing_api_environment: tuple[
        TestClient, sessionmaker[Session], FakeEmbedder, FakeVectorStore
    ],
) -> None:
    client, factory, embedder, _ = indexing_api_environment
    add_document(factory, chunks=())

    response = client.post(
        "/documents/1/index",
        headers=authorization_header(42),
    )

    assert response.status_code == 409
    assert embedder.calls == []


def test_overlapping_api_request_cannot_claim_same_document(
    indexing_api_environment: tuple[
        TestClient, sessionmaker[Session], FakeEmbedder, FakeVectorStore
    ],
) -> None:
    client, factory, embedder, _ = indexing_api_environment
    add_document(factory)
    competing_statuses: list[int] = []

    def competing_request() -> None:
        competing_statuses.append(
            client.post(
                "/documents/1/index",
                headers=authorization_header(42),
            ).status_code
        )

    embedder.callback = competing_request
    response = client.post(
        "/documents/1/index",
        headers=authorization_header(42),
    )

    assert response.status_code == 200
    assert competing_statuses == [429]


@pytest.mark.parametrize(
    ("status_value", "rag_status", "chunks", "expected_can_index"),
    [
        ("READY", "PENDING", ("Chunk",), True),
        ("READY", "FAILED", ("Chunk",), True),
        ("READY", "READY", ("Chunk",), False),
        ("READY", "INDEXING", ("Chunk",), False),
        ("UPLOADED", "PENDING", ("Chunk",), False),
        ("READY", "PENDING", (), False),
    ],
)
def test_rag_status_and_can_index_are_postgresql_backed(
    indexing_api_environment: tuple[
        TestClient, sessionmaker[Session], FakeEmbedder, FakeVectorStore
    ],
    status_value: str,
    rag_status: str,
    chunks: tuple[str, ...],
    expected_can_index: bool,
) -> None:
    client, factory, embedder, vector_store = indexing_api_environment
    add_document(
        factory,
        status=status_value,
        rag_status=rag_status,
        chunks=chunks,
    )

    response = client.get(
        "/documents/1/rag-status",
        headers=authorization_header(42),
    )

    assert response.status_code == 200
    assert response.json() == {
        "document_id": 1,
        "status": status_value,
        "rag_status": rag_status,
        "chunk_count": len(chunks),
        "indexed_at": None,
        "can_index": expected_can_index,
    }
    assert embedder.calls == []
    assert vector_store.records == {}


def test_missing_api_key_is_safe_and_does_not_claim(
    indexing_api_environment: tuple[
        TestClient, sessionmaker[Session], FakeEmbedder, FakeVectorStore
    ],
) -> None:
    client, factory, _, _ = indexing_api_environment
    add_document(factory)
    app.dependency_overrides.pop(get_rag_indexing_resources)
    app.dependency_overrides[get_settings] = lambda: replace(
        get_settings(),
        gemini_api_key=None,
    )

    response = client.post(
        "/documents/1/index",
        headers=authorization_header(42),
    )

    assert response.status_code == 503
    assert stored_document(factory).rag_status == "PENDING"
    assert "key" not in response.text.lower()


def test_external_clients_are_not_created_for_unindexable_document(
    indexing_api_environment: tuple[
        TestClient, sessionmaker[Session], FakeEmbedder, FakeVectorStore
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, factory, _, _ = indexing_api_environment
    add_document(factory, status="UPLOADED")
    app.dependency_overrides.pop(get_rag_indexing_resources)
    app.dependency_overrides[get_settings] = lambda: replace(
        get_settings(),
        gemini_api_key="test-only-not-a-real-key",
    )

    def fail_constructor(*args: object, **kwargs: object) -> None:
        raise AssertionError("External clients must remain lazy.")

    monkeypatch.setattr(
        rag_dependencies,
        "GeminiEmbeddingService",
        fail_constructor,
    )
    monkeypatch.setattr(
        rag_dependencies,
        "ChromaVectorStore",
        fail_constructor,
    )

    response = client.post(
        "/documents/1/index",
        headers=authorization_header(42),
    )

    assert response.status_code == 409
    assert stored_document(factory).rag_status == "PENDING"


@pytest.mark.parametrize("failure_source", ["gemini", "chroma"])
def test_external_service_failure_is_safe_and_marks_failed(
    indexing_api_environment: tuple[
        TestClient, sessionmaker[Session], FakeEmbedder, FakeVectorStore
    ],
    failure_source: str,
) -> None:
    client, factory, _, _ = indexing_api_environment
    add_document(factory)
    secret = "secret-api-key-and-private-content"
    embedder = FakeEmbedder(
        error=RuntimeError(secret) if failure_source == "gemini" else None
    )
    vector_store = FakeVectorStore(
        error=RuntimeError(secret) if failure_source == "chroma" else None
    )
    app.dependency_overrides[get_rag_indexing_resources] = lambda: (
        RagIndexingResources(embedder, vector_store)
    )

    response = client.post(
        "/documents/1/index",
        headers=authorization_header(42),
    )

    assert response.status_code == 503
    assert stored_document(factory).rag_status == "FAILED"
    assert secret not in response.text
    assert "Nội dung học tập" not in response.text
    assert "private-secret-key" not in response.text


def test_success_response_does_not_expose_document_content_or_storage_key(
    indexing_api_environment: tuple[
        TestClient, sessionmaker[Session], FakeEmbedder, FakeVectorStore
    ],
) -> None:
    client, factory, _, _ = indexing_api_environment
    add_document(factory)

    response = client.post(
        "/documents/1/index",
        headers=authorization_header(42),
    )

    assert response.status_code == 200
    assert "Nội dung học tập" not in response.text
    assert "private-secret-key" not in response.text
    assert "api_key" not in response.text.lower()


def test_indexing_capacity_limit_returns_429_without_claim_or_embedding(
    indexing_api_environment: tuple[
        TestClient, sessionmaker[Session], FakeEmbedder, FakeVectorStore
    ],
) -> None:
    client, factory, embedder, vector_store = indexing_api_environment
    add_document(factory)
    coordinator = FakeCapacityCoordinator(
        SummaryConcurrencyLimitError("test capacity exhausted")
    )
    app.dependency_overrides[get_rag_indexing_resources] = lambda: (
        RagIndexingResources(
            embedder,
            vector_store,
            concurrency_coordinator=coordinator,
        )
    )

    response = client.post(
        "/documents/1/index",
        headers=authorization_header(42),
    )

    assert response.status_code == 429
    assert response.headers["retry-after"] == "3"
    assert stored_document(factory).rag_status == "PENDING"
    assert embedder.calls == []


def test_indexing_coordination_failure_returns_503_without_claim(
    indexing_api_environment: tuple[
        TestClient, sessionmaker[Session], FakeEmbedder, FakeVectorStore
    ],
) -> None:
    client, factory, embedder, vector_store = indexing_api_environment
    add_document(factory)
    coordinator = FakeCapacityCoordinator(
        SummaryConcurrencyError("test coordinator unavailable")
    )
    app.dependency_overrides[get_rag_indexing_resources] = lambda: (
        RagIndexingResources(
            embedder,
            vector_store,
            concurrency_coordinator=coordinator,
        )
    )

    response = client.post(
        "/documents/1/index",
        headers=authorization_header(42),
    )

    assert response.status_code == 503
    assert stored_document(factory).rag_status == "PENDING"
    assert embedder.calls == []


def test_indexing_releases_capacity_after_provider_failure(
    indexing_api_environment: tuple[
        TestClient, sessionmaker[Session], FakeEmbedder, FakeVectorStore
    ],
) -> None:
    client, factory, _, vector_store = indexing_api_environment
    add_document(factory)
    embedder = FakeEmbedder(error=RuntimeError("test-only failure"))
    coordinator = FakeCapacityCoordinator()
    app.dependency_overrides[get_rag_indexing_resources] = lambda: (
        RagIndexingResources(
            embedder,
            vector_store,
            concurrency_coordinator=coordinator,
        )
    )

    response = client.post(
        "/documents/1/index",
        headers=authorization_header(42),
    )

    assert response.status_code == 503
    assert coordinator.entries == 1
    assert coordinator.exits == 1
    assert coordinator.active == 0
