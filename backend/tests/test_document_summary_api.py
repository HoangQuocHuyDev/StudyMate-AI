"""Isolated API tests for document summary generation and listing."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

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

import app.routers.summaries as summary_router
import app.dependencies.summary as summary_dependencies
from app.core.security import create_access_token
from app.db.session import get_db
from app.dependencies.summary import SummaryResources, get_summary_resources
from app.main import app
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.document_deletion_job import DocumentDeletionJob
from app.models.document_summary import DocumentSummary
from app.models.user import User
from app.services.summary.document_summary import (
    DocumentSummaryDeadlineExceededError,
    DocumentSummaryPersistenceError,
)
from app.services.summary.concurrency import (
    SummaryConcurrencyError,
    SummaryConcurrencyLimitError,
    SummaryGenerationBusyError,
)
from app.services.summary.gemini_summary import (
    GeneratedSummary,
    GeminiSummaryRateLimitError,
    GeminiSummaryTimeoutError,
)


def authorization_header(user_id: int) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id, 0)}"}


class FakeSummaryProvider:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.error: Exception | None = None
        self.empty_response = False
        self.close_count = 0

    def generate_summary(
        self,
        content: str,
        summary_type: str,
        *,
        stage: str,
        timeout_seconds: float | None = None,
    ) -> GeneratedSummary:
        assert timeout_seconds is not None and timeout_seconds > 0
        self.calls.append((content, summary_type, stage))
        if self.error is not None:
            raise self.error
        return GeneratedSummary(
            content="" if self.empty_response else f"Tóm tắt {summary_type}",
            model_name="fake-gemini",
        )

    def close(self) -> None:
        self.close_count += 1


@pytest.fixture
def summary_api_environment(
    client: TestClient,
    tmp_path: Path,
) -> Iterator[
    tuple[TestClient, sessionmaker[Session], FakeSummaryProvider]
]:
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'summary-api.sqlite3'}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def configure_sqlite(connection: object, record: object) -> None:
        cursor = connection.cursor()  # type: ignore[attr-defined]
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
    for table in (
        Document.__table__,
        DocumentDeletionJob.__table__,
        DocumentChunk.__table__,
        DocumentSummary.__table__,
    ):
        table.to_metadata(metadata)
    metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    provider = FakeSummaryProvider()

    def override_database() -> Iterator[Session]:
        with factory() as db:
            yield db

    def override_resources() -> Iterator[SummaryResources]:
        try:
            yield SummaryResources(provider=provider)
        finally:
            provider.close()

    app.dependency_overrides[get_db] = override_database
    app.dependency_overrides[get_summary_resources] = override_resources
    yield client, factory, provider
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_summary_resources, None)
    engine.dispose()


def add_user(factory: sessionmaker[Session], user_id: int) -> None:
    with factory() as db:
        if db.get(User, user_id) is None:
            db.add(User(
                id=user_id,
                full_name=f"User {user_id}",
                username=f"user_{user_id}",
                password_hash="test-hash",
                role="USER",
                is_active=True,
                created_at=datetime.now(timezone.utc),
            ))
            db.commit()


def add_document(
    factory: sessionmaker[Session],
    *,
    document_id: int = 1,
    user_id: int = 7,
    status: str = "READY",
    chunks: list[str] | None = None,
) -> None:
    add_user(factory, user_id)
    now = datetime.now(timezone.utc)
    with factory() as db:
        db.add(Document(
            id=document_id,
            user_id=user_id,
            title="Tài liệu kiểm thử",
            original_filename="summary.docx",
            storage_key=f"users/{user_id}/summary-api-{document_id}",
            file_type="DOCX",
            mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            file_size=100,
            status=status,
            rag_status="PENDING",
            created_at=now,
            updated_at=now,
        ))
        db.flush()
        for index, content in enumerate(chunks or []):
            db.add(DocumentChunk(
                id=document_id * 100 + index + 1,
                document_id=document_id,
                chunk_index=index,
                content=content,
                start_char=index * 300_000,
                end_char=index * 300_000 + len(content),
                character_count=len(content),
                page_number=None,
                created_at=now,
            ))
        db.commit()


def add_summary(
    factory: sessionmaker[Session],
    *,
    summary_type: str,
    content: str | None = None,
) -> int:
    with factory() as db:
        summary = DocumentSummary(
            document_id=1,
            summary_type=summary_type,
            content=content or f"Nội dung {summary_type}",
            model_name="fake-gemini",
        )
        db.add(summary)
        db.commit()
        return summary.id


def generate(
    client: TestClient,
    summary_type: str = "STANDARD",
    *,
    user_id: int = 7,
) -> object:
    return client.post(
        "/summaries/generate",
        headers=authorization_header(user_id),
        json={"document_id": 1, "summary_type": summary_type},
    )


def test_post_and_get_require_jwt(
    summary_api_environment: tuple[
        TestClient, sessionmaker[Session], FakeSummaryProvider
    ],
) -> None:
    client, _, provider = summary_api_environment
    assert client.post(
        "/summaries/generate",
        json={"document_id": 1, "summary_type": "SHORT"},
    ).status_code == 401
    assert client.get("/summaries?document_id=1").status_code == 401
    assert provider.calls == []


def test_other_user_cannot_generate_or_list_summaries(
    summary_api_environment: tuple[
        TestClient, sessionmaker[Session], FakeSummaryProvider
    ],
) -> None:
    client, factory, provider = summary_api_environment
    add_document(factory, user_id=8, chunks=["Nội dung"])
    add_user(factory, 7)
    assert generate(client, user_id=7).status_code == 404
    assert client.get(
        "/summaries?document_id=1",
        headers=authorization_header(7),
    ).status_code == 404
    assert provider.calls == []


@pytest.mark.parametrize("summary_type", ["SHORT", "STANDARD", "DETAILED"])
def test_generate_supported_summary_types(
    summary_api_environment: tuple[
        TestClient, sessionmaker[Session], FakeSummaryProvider
    ],
    summary_type: str,
) -> None:
    client, factory, provider = summary_api_environment
    add_document(factory, chunks=["Nội dung tài liệu"])
    response = generate(client, summary_type)
    body = response.json()
    assert response.status_code == 200
    assert body["summary_type"] == summary_type
    assert body["content"] == f"Tóm tắt {summary_type}"
    assert body["model_name"] == "fake-gemini"
    assert body["from_cache"] is False
    assert "created_at" in body and "updated_at" in body
    assert len(provider.calls) == 1
    assert provider.close_count == 1


@pytest.mark.parametrize("summary_type", ["CUSTOM", "", "short", None])
def test_invalid_summary_type_returns_422_without_provider(
    summary_api_environment: tuple[
        TestClient, sessionmaker[Session], FakeSummaryProvider
    ],
    summary_type: object,
) -> None:
    client, factory, provider = summary_api_environment
    add_user(factory, 7)
    response = client.post(
        "/summaries/generate",
        headers=authorization_header(7),
        json={"document_id": 1, "summary_type": summary_type},
    )
    assert response.status_code == 422
    assert provider.calls == []


@pytest.mark.parametrize(
    ("status_value", "chunks"),
    [("UPLOADED", ["Nội dung"]), ("READY", [])],
)
def test_document_must_be_ready_and_have_chunks(
    summary_api_environment: tuple[
        TestClient, sessionmaker[Session], FakeSummaryProvider
    ],
    status_value: str,
    chunks: list[str],
) -> None:
    client, factory, provider = summary_api_environment
    add_document(factory, status=status_value, chunks=chunks)
    response = generate(client)
    assert response.status_code == 409
    assert provider.calls == []


def test_cache_miss_calls_provider_and_cache_hit_does_not(
    summary_api_environment: tuple[
        TestClient, sessionmaker[Session], FakeSummaryProvider
    ],
) -> None:
    client, factory, provider = summary_api_environment
    add_document(factory, chunks=["Nội dung"])
    first = generate(client, "SHORT")
    second = generate(client, "SHORT")
    assert first.status_code == 200 and first.json()["from_cache"] is False
    assert second.status_code == 200 and second.json()["from_cache"] is True
    assert first.json()["summary_id"] == second.json()["summary_id"]
    assert len(provider.calls) == 1


def test_cache_hit_works_with_default_lazy_dependency_and_no_api_key(
    summary_api_environment: tuple[
        TestClient, sessionmaker[Session], FakeSummaryProvider
    ],
) -> None:
    client, factory, _ = summary_api_environment
    add_document(factory, chunks=["Nội dung"])
    summary_id = add_summary(factory, summary_type="SHORT")
    app.dependency_overrides.pop(get_summary_resources, None)

    response = generate(client, "SHORT")

    assert response.status_code == 200
    assert response.json()["summary_id"] == summary_id
    assert response.json()["from_cache"] is True


def test_default_dependency_creates_provider_only_on_miss_and_closes_it(
    summary_api_environment: tuple[
        TestClient, sessionmaker[Session], FakeSummaryProvider
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, factory, _ = summary_api_environment
    add_document(factory, chunks=["Nội dung"])
    created: list[object] = []

    class FakeGeminiProvider:
        def __init__(self, settings: object) -> None:
            self.closed = False
            created.append(self)

        def generate_summary(
            self,
            content: str,
            summary_type: str,
            *,
            stage: str,
            timeout_seconds: float | None = None,
        ) -> GeneratedSummary:
            assert timeout_seconds is not None and timeout_seconds > 0
            return GeneratedSummary("Tóm tắt lazy", "fake-lazy-gemini")

        def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(
        summary_dependencies,
        "GeminiSummaryProvider",
        FakeGeminiProvider,
    )
    app.dependency_overrides.pop(get_summary_resources, None)

    response = generate(client, "STANDARD")

    assert response.status_code == 200
    assert response.json()["content"] == "Tóm tắt lazy"
    assert len(created) == 1
    assert created[0].closed is True


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (GeminiSummaryTimeoutError("secret timeout"), 503),
        (GeminiSummaryRateLimitError("secret quota"), 429),
    ],
)
def test_provider_failures_are_safely_mapped(
    summary_api_environment: tuple[
        TestClient, sessionmaker[Session], FakeSummaryProvider
    ],
    error: Exception,
    expected_status: int,
) -> None:
    client, factory, provider = summary_api_environment
    add_document(factory, chunks=["PRIVATE_DOCUMENT_CONTENT"])
    provider.error = error
    response = generate(client)
    assert response.status_code == expected_status
    assert "secret" not in response.text.lower()
    assert "private_document_content" not in response.text.lower()


def test_overall_deadline_returns_safe_504(
    summary_api_environment: tuple[
        TestClient, sessionmaker[Session], FakeSummaryProvider
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, factory, _ = summary_api_environment
    add_document(factory, chunks=["PRIVATE_DOCUMENT_CONTENT"])
    monkeypatch.setattr(
        summary_router,
        "summarize_document",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            DocumentSummaryDeadlineExceededError("secret deadline")
        ),
    )
    response = generate(client)
    assert response.status_code == 504
    assert "vượt quá thời gian" in response.json()["detail"]
    assert "secret" not in response.text.lower()
    assert "private_document_content" not in response.text.lower()


def test_empty_provider_response_returns_503_and_is_not_saved(
    summary_api_environment: tuple[
        TestClient, sessionmaker[Session], FakeSummaryProvider
    ],
) -> None:
    client, factory, provider = summary_api_environment
    add_document(factory, chunks=["Nội dung"])
    provider.empty_response = True
    response = generate(client)
    assert response.status_code == 503
    with factory() as db:
        assert db.query(DocumentSummary).count() == 0


def test_oversized_document_returns_413_before_provider(
    summary_api_environment: tuple[
        TestClient, sessionmaker[Session], FakeSummaryProvider
    ],
) -> None:
    client, factory, provider = summary_api_environment
    add_document(factory, chunks=["X" * 240_001])
    response = generate(client)
    assert response.status_code == 413
    assert provider.calls == []


def test_persistence_error_is_safe(
    summary_api_environment: tuple[
        TestClient, sessionmaker[Session], FakeSummaryProvider
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, factory, _ = summary_api_environment
    add_document(factory, chunks=["PRIVATE_DOCUMENT_CONTENT"])
    monkeypatch.setattr(
        summary_router,
        "summarize_document",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            DocumentSummaryPersistenceError("secret SQL storage_key")
        ),
    )
    response = generate(client)
    assert response.status_code == 500
    assert "secret" not in response.text.lower()
    assert "storage_key" not in response.text.lower()


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (SummaryGenerationBusyError("secret"), 409),
        (SummaryConcurrencyLimitError("secret"), 429),
        (SummaryConcurrencyError("secret"), 503),
    ],
)
def test_concurrency_failures_are_mapped_safely(
    summary_api_environment: tuple[
        TestClient, sessionmaker[Session], FakeSummaryProvider
    ],
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    expected_status: int,
) -> None:
    client, factory, _ = summary_api_environment
    add_document(factory, chunks=["PRIVATE_DOCUMENT_CONTENT"])
    monkeypatch.setattr(
        summary_router,
        "summarize_document",
        lambda *args, **kwargs: (_ for _ in ()).throw(error),
    )
    response = generate(client)
    assert response.status_code == expected_status
    assert "secret" not in response.text.lower()
    assert "private_document_content" not in response.text.lower()
    if expected_status == 429:
        assert response.headers["retry-after"] == "5"


def test_get_empty_list_does_not_initialize_ai_resources(
    summary_api_environment: tuple[
        TestClient, sessionmaker[Session], FakeSummaryProvider
    ],
) -> None:
    client, factory, provider = summary_api_environment
    add_document(factory, chunks=["Nội dung"])

    def forbidden_resources() -> None:
        raise AssertionError("GET must not initialize Gemini or ChromaDB")

    app.dependency_overrides[get_summary_resources] = forbidden_resources
    response = client.get(
        "/summaries?document_id=1",
        headers=authorization_header(7),
    )
    assert response.status_code == 200
    assert response.json() == {"document_id": 1, "items": []}
    assert provider.calls == []


def test_get_returns_all_saved_summaries_in_business_order(
    summary_api_environment: tuple[
        TestClient, sessionmaker[Session], FakeSummaryProvider
    ],
) -> None:
    client, factory, provider = summary_api_environment
    add_document(factory, chunks=["Nội dung"])
    for summary_type in ("DETAILED", "SHORT", "STANDARD"):
        add_summary(factory, summary_type=summary_type)
    response = client.get(
        "/summaries?document_id=1",
        headers=authorization_header(7),
    )
    body = response.json()
    assert response.status_code == 200
    assert body["document_id"] == 1
    assert [item["summary_type"] for item in body["items"]] == [
        "SHORT",
        "STANDARD",
        "DETAILED",
    ]
    assert all(set(item) == {
        "summary_id",
        "document_id",
        "summary_type",
        "content",
        "model_name",
        "created_at",
        "updated_at",
    } for item in body["items"])
    assert provider.calls == []
