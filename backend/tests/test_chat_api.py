"""Isolated API tests for synchronous RAG chat and persisted history."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
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
    func,
    select,
)
from sqlalchemy.orm import Session, sessionmaker

import app.dependencies.rag as rag_dependencies
from app.core.security import create_access_token
from app.core.config import (
    DEFAULT_CHAT_DEADLINE_SECONDS,
    _load_chat_deadline_seconds,
    get_settings,
)
from app.db.session import get_db
from app.dependencies.rag import RagChatResources, get_rag_chat_resources
from app.main import app
from app.models.chat_citation import ChatCitation
from app.models.chat_message import ChatMessage
from app.models.chat_session import ChatSession
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.document_deletion_job import DocumentDeletionJob
from app.models.user import User
from app.services.rag.answer_service import (
    GeminiAnswerRateLimitError,
    GeneratedAnswer,
)
from app.services.rag.document_retrieval import RetrievedDocumentChunk
from app.services.summary.concurrency import (
    SummaryConcurrencyError,
    SummaryConcurrencyLimitError,
)


def authorization_header(user_id: int) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id, 0)}"}


def test_chat_deadline_configuration_has_safe_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CHAT_DEADLINE_SECONDS", raising=False)
    assert _load_chat_deadline_seconds() == DEFAULT_CHAT_DEADLINE_SECONDS == 60


@pytest.mark.parametrize("value", ["", "four", "4", "601"])
def test_chat_deadline_configuration_rejects_invalid_values(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv("CHAT_DEADLINE_SECONDS", value)
    with pytest.raises(RuntimeError):
        _load_chat_deadline_seconds()


class FakeRetrieval:
    def __init__(self) -> None:
        self.error: Exception | None = None
        self.calls: list[dict[str, object]] = []

    def __call__(
        self,
        db: Session,
        *,
        document_id: int,
        user_id: int,
        query: str,
        deadline: object | None = None,
    ) -> list[RetrievedDocumentChunk]:
        assert not db.in_transaction()
        self.calls.append(
            {"document_id": document_id, "user_id": user_id, "query": query}
        )
        if self.error is not None:
            raise self.error
        return [
            RetrievedDocumentChunk(
                chunk_id=document_id * 100 + 1,
                document_id=document_id,
                chunk_index=0,
                content="Nội dung PostgreSQL",
                page_number=1,
                distance=0.1,
            )
        ]


class FakeAnswer:
    def __init__(self) -> None:
        self.error: Exception | None = None
        self.calls: list[tuple[str, tuple[RetrievedDocumentChunk, ...]]] = []

    def generate_answer(
        self,
        question: str,
        retrieved_chunks: Sequence[RetrievedDocumentChunk],
        *,
        timeout_seconds: float | None = None,
    ) -> GeneratedAnswer:
        self.calls.append((question, tuple(retrieved_chunks)))
        if self.error is not None:
            raise self.error
        return GeneratedAnswer(
            answer_text="Tài liệu nói về AI [Nguồn 1]",
            cited_chunk_ids=[retrieved_chunks[0].chunk_id],
            model_name="fake-gemini",
        )


@pytest.fixture
def chat_api_environment(
    client: TestClient,
    tmp_path: Path,
) -> Iterator[
    tuple[
        TestClient,
        sessionmaker[Session],
        FakeRetrieval,
        FakeAnswer,
    ]
]:
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'chat-api.sqlite3'}",
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
        ChatSession.__table__,
        ChatMessage.__table__,
        ChatCitation.__table__,
    ):
        table.to_metadata(metadata)
    metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    retrieval = FakeRetrieval()
    answer = FakeAnswer()
    resources = RagChatResources(retrieval, answer)

    def override_database() -> Iterator[Session]:
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_database
    app.dependency_overrides[get_rag_chat_resources] = lambda: resources
    yield client, factory, retrieval, answer
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_rag_chat_resources, None)
    app.dependency_overrides.pop(get_settings, None)
    engine.dispose()


def add_user(factory: sessionmaker[Session], user_id: int) -> None:
    with factory() as db:
        if db.get(User, user_id) is None:
            db.add(
                User(
                    id=user_id,
                    full_name=f"User {user_id}",
                    username=f"user_{user_id}",
                    password_hash="test-hash",
                    role="USER",
                    is_active=True,
                    created_at=datetime.now(timezone.utc),
                )
            )
            db.commit()


def add_document(
    factory: sessionmaker[Session],
    *,
    document_id: int = 1,
    user_id: int = 42,
    status: str = "READY",
    rag_status: str = "READY",
) -> None:
    add_user(factory, user_id)
    now = datetime.now(timezone.utc)
    content = "Nội dung PostgreSQL"
    with factory() as db:
        db.add(
            Document(
                id=document_id,
                user_id=user_id,
                title="Tài liệu AI",
                original_filename="ai.docx",
                storage_key=(
                    f"users/{user_id}/document-{document_id}-private-storage-key"
                ),
                file_type="DOCX",
                mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                file_size=100,
                status=status,
                rag_status=rag_status,
                created_at=now,
                updated_at=now,
            )
        )
        db.flush()
        db.add(
            DocumentChunk(
                id=document_id * 100 + 1,
                document_id=document_id,
                chunk_index=0,
                content=content,
                start_char=0,
                end_char=len(content),
                character_count=len(content),
                page_number=1,
                created_at=now,
            )
        )
        db.commit()


def add_session(
    factory: sessionmaker[Session],
    *,
    document_id: int = 1,
    title: str = "Phiên học tập",
    updated_at: datetime | None = None,
) -> int:
    timestamp = updated_at or datetime.now(timezone.utc)
    with factory() as db:
        session = ChatSession(
            document_id=document_id,
            title=title,
            created_at=timestamp,
            updated_at=timestamp,
        )
        db.add(session)
        db.commit()
        return session.id


def add_history(factory: sessionmaker[Session], session_id: int) -> None:
    now = datetime.now(timezone.utc)
    with factory() as db:
        user_message = ChatMessage(
            session_id=session_id,
            sequence_no=0,
            role="USER",
            content="Tài liệu nói gì?",
            created_at=now,
        )
        assistant_message = ChatMessage(
            session_id=session_id,
            sequence_no=1,
            role="ASSISTANT",
            content="Tài liệu nói về AI.",
            created_at=now,
        )
        db.add_all([user_message, assistant_message])
        db.flush()
        db.add(
            ChatCitation(
                message_id=assistant_message.id,
                document_chunk_id=101,
                citation_order=0,
                created_at=now,
            )
        )
        db.commit()


def add_message_range(
    factory: sessionmaker[Session],
    session_id: int,
    *,
    start: int,
    stop: int,
    cited_sequence_no: int | None = None,
) -> None:
    """Persist deterministic history without involving Gemini or ChromaDB."""

    now = datetime.now(timezone.utc)
    with factory() as db:
        messages = [
            ChatMessage(
                session_id=session_id,
                sequence_no=sequence_no,
                role="USER" if sequence_no % 2 == 0 else "ASSISTANT",
                content=f"Message {sequence_no}",
                created_at=now + timedelta(seconds=sequence_no),
            )
            for sequence_no in range(start, stop)
        ]
        db.add_all(messages)
        db.flush()
        if cited_sequence_no is not None:
            cited_message = next(
                item
                for item in messages
                if item.sequence_no == cited_sequence_no
            )
            if cited_message.role != "ASSISTANT":
                raise AssertionError("Only assistant messages can be cited.")
            db.add(
                ChatCitation(
                    message_id=cited_message.id,
                    document_chunk_id=101,
                    citation_order=0,
                    created_at=now,
                )
            )
        db.commit()


def test_chat_endpoints_require_jwt(
    chat_api_environment: tuple[
        TestClient, sessionmaker[Session], FakeRetrieval, FakeAnswer
    ],
) -> None:
    client, _, _, _ = chat_api_environment
    assert client.post("/chat/ask", json={"document_id": 1, "question": "Q"}).status_code == 401
    assert client.get("/chat/sessions?document_id=1").status_code == 401
    assert client.get("/chat/sessions/1/messages").status_code == 401
    assert client.get("/chat/sessions/1/messages/cursor").status_code == 401
    assert client.get(
        "/chat/citations/101?session_id=1&message_id=1"
    ).status_code == 401


def test_other_user_cannot_ask_document(
    chat_api_environment: tuple[
        TestClient, sessionmaker[Session], FakeRetrieval, FakeAnswer
    ],
) -> None:
    client, factory, retrieval, _ = chat_api_environment
    add_document(factory, user_id=8)
    add_user(factory, 42)
    response = client.post(
        "/chat/ask",
        headers=authorization_header(42),
        json={"document_id": 1, "question": "Nội dung gì?"},
    )
    assert response.status_code == 404
    assert retrieval.calls == []


def test_ask_success_returns_persisted_messages_and_citation(
    chat_api_environment: tuple[
        TestClient, sessionmaker[Session], FakeRetrieval, FakeAnswer
    ],
) -> None:
    client, factory, _, _ = chat_api_environment
    add_document(factory)
    response = client.post(
        "/chat/ask",
        headers=authorization_header(42),
        json={"document_id": 1, "question": "Tài liệu này nói gì?"},
    )
    body = response.json()
    assert response.status_code == 200
    assert body["answer_text"] == "Tài liệu nói về AI [Nguồn 1]"
    assert body["model_name"] == "fake-gemini"
    assert body["citations"] == [
        {
            "chunk_id": 101,
            "chunk_index": 0,
            "page_number": 1,
            "citation_order": 0,
        }
    ]
    with factory() as db:
        assert len(db.scalars(select(ChatMessage)).all()) == 2
        assert len(db.scalars(select(ChatCitation)).all()) == 1


def test_ask_continues_existing_session(
    chat_api_environment: tuple[
        TestClient, sessionmaker[Session], FakeRetrieval, FakeAnswer
    ],
) -> None:
    client, factory, _, _ = chat_api_environment
    add_document(factory)
    session_id = add_session(factory)
    add_history(factory, session_id)
    response = client.post(
        "/chat/ask",
        headers=authorization_header(42),
        json={
            "document_id": 1,
            "question": "Giải thích thêm",
            "session_id": session_id,
        },
    )
    assert response.status_code == 200
    assert response.json()["session_id"] == session_id
    with factory() as db:
        sequence = db.scalars(
            select(ChatMessage.sequence_no)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.sequence_no)
        ).all()
    assert sequence == [0, 1, 2, 3]


def test_session_from_another_document_is_rejected(
    chat_api_environment: tuple[
        TestClient, sessionmaker[Session], FakeRetrieval, FakeAnswer
    ],
) -> None:
    client, factory, _, _ = chat_api_environment
    add_document(factory, document_id=1)
    add_document(factory, document_id=2)
    session_id = add_session(factory, document_id=2)
    response = client.post(
        "/chat/ask",
        headers=authorization_header(42),
        json={"document_id": 1, "question": "Q", "session_id": session_id},
    )
    assert response.status_code == 404


@pytest.mark.parametrize(
    ("status_value", "rag_status"),
    [("UPLOADED", "READY"), ("READY", "PENDING")],
)
def test_document_not_ready_returns_conflict(
    chat_api_environment: tuple[
        TestClient, sessionmaker[Session], FakeRetrieval, FakeAnswer
    ],
    status_value: str,
    rag_status: str,
) -> None:
    client, factory, _, _ = chat_api_environment
    add_document(factory, status=status_value, rag_status=rag_status)
    response = client.post(
        "/chat/ask",
        headers=authorization_header(42),
        json={"document_id": 1, "question": "Q"},
    )
    assert response.status_code == 409


@pytest.mark.parametrize("question", ["", "   ", "x" * 2001])
def test_invalid_question_returns_422(
    chat_api_environment: tuple[
        TestClient, sessionmaker[Session], FakeRetrieval, FakeAnswer
    ],
    question: str,
) -> None:
    client, factory, _, _ = chat_api_environment
    add_document(factory)
    response = client.post(
        "/chat/ask",
        headers=authorization_header(42),
        json={"document_id": 1, "question": question},
    )
    assert response.status_code == 422


@pytest.mark.parametrize("provider", ["retrieval", "answer"])
def test_provider_errors_are_safe_and_return_503(
    chat_api_environment: tuple[
        TestClient, sessionmaker[Session], FakeRetrieval, FakeAnswer
    ],
    provider: str,
) -> None:
    client, factory, retrieval, answer = chat_api_environment
    add_document(factory)
    secret = "secret-api-key private-storage-key chunk-content"
    if provider == "retrieval":
        retrieval.error = RuntimeError(secret)
    else:
        answer.error = RuntimeError(secret)
    response = client.post(
        "/chat/ask",
        headers=authorization_header(42),
        json={"document_id": 1, "question": "Q"},
    )
    assert response.status_code == 503
    assert secret not in response.text
    assert "private-storage-key" not in response.text


def test_explicit_answer_rate_limit_returns_429(
    chat_api_environment: tuple[
        TestClient, sessionmaker[Session], FakeRetrieval, FakeAnswer
    ],
) -> None:
    client, factory, _, answer = chat_api_environment
    add_document(factory)
    answer.error = GeminiAnswerRateLimitError("sensitive quota detail")
    response = client.post(
        "/chat/ask",
        headers=authorization_header(42),
        json={"document_id": 1, "question": "Q"},
    )
    assert response.status_code == 429
    assert "sensitive" not in response.text


class RejectingCapacityCoordinator:
    def __init__(self, error: Exception) -> None:
        self.error = error

    @contextmanager
    def capacity(self, user_id: int) -> Iterator[None]:
        assert user_id == 42
        raise self.error
        yield


def test_chat_capacity_limit_returns_429_with_retry_after(
    chat_api_environment: tuple[
        TestClient, sessionmaker[Session], FakeRetrieval, FakeAnswer
    ],
) -> None:
    client, factory, retrieval, answer = chat_api_environment
    add_document(factory)
    app.dependency_overrides[get_rag_chat_resources] = lambda: RagChatResources(
        retrieval,
        answer,
        concurrency_coordinator=RejectingCapacityCoordinator(
            SummaryConcurrencyLimitError("capacity exhausted")
        ),
    )

    response = client.post(
        "/chat/ask",
        headers=authorization_header(42),
        json={"document_id": 1, "question": "Q"},
    )

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "5"
    assert retrieval.calls == []
    assert answer.calls == []
    with factory() as db:
        assert db.scalar(select(ChatMessage.id)) is None


def test_chat_coordination_failure_returns_safe_503(
    chat_api_environment: tuple[
        TestClient, sessionmaker[Session], FakeRetrieval, FakeAnswer
    ],
) -> None:
    client, factory, retrieval, answer = chat_api_environment
    add_document(factory)
    secret = "sensitive coordination detail"
    app.dependency_overrides[get_rag_chat_resources] = lambda: RagChatResources(
        retrieval,
        answer,
        concurrency_coordinator=RejectingCapacityCoordinator(
            SummaryConcurrencyError(secret)
        ),
    )

    response = client.post(
        "/chat/ask",
        headers=authorization_header(42),
        json={"document_id": 1, "question": "Q"},
    )

    assert response.status_code == 503
    assert secret not in response.text
    assert retrieval.calls == []
    assert answer.calls == []


def test_missing_api_key_returns_safe_503_without_external_calls(
    chat_api_environment: tuple[
        TestClient, sessionmaker[Session], FakeRetrieval, FakeAnswer
    ],
) -> None:
    client, factory, retrieval, answer = chat_api_environment
    add_document(factory)
    app.dependency_overrides.pop(get_rag_chat_resources)
    app.dependency_overrides[get_settings] = lambda: replace(
        get_settings(),
        gemini_api_key=None,
    )
    response = client.post(
        "/chat/ask",
        headers=authorization_header(42),
        json={"document_id": 1, "question": "Q"},
    )
    app.dependency_overrides.pop(get_settings, None)
    assert response.status_code == 503
    assert retrieval.calls == []
    assert answer.calls == []
    assert "key" not in response.text.lower()


def test_unready_document_does_not_construct_external_clients(
    chat_api_environment: tuple[
        TestClient, sessionmaker[Session], FakeRetrieval, FakeAnswer
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, factory, _, _ = chat_api_environment
    add_document(factory, status="UPLOADED")
    app.dependency_overrides.pop(get_rag_chat_resources)
    app.dependency_overrides[get_settings] = lambda: replace(
        get_settings(),
        gemini_api_key="test-only-not-a-real-key",
    )

    def forbidden_constructor(*args: object, **kwargs: object) -> None:
        raise AssertionError("External client constructors must remain lazy")

    monkeypatch.setattr(
        rag_dependencies,
        "GeminiEmbeddingService",
        forbidden_constructor,
    )
    monkeypatch.setattr(
        rag_dependencies,
        "GeminiAnswerService",
        forbidden_constructor,
    )
    monkeypatch.setattr(
        rag_dependencies,
        "ChromaVectorStore",
        forbidden_constructor,
    )
    response = client.post(
        "/chat/ask",
        headers=authorization_header(42),
        json={"document_id": 1, "question": "Q"},
    )
    assert response.status_code == 409


def test_sessions_are_owner_scoped_ordered_and_paginated(
    chat_api_environment: tuple[
        TestClient, sessionmaker[Session], FakeRetrieval, FakeAnswer
    ],
) -> None:
    client, factory, _, _ = chat_api_environment
    add_document(factory)
    base = datetime(2025, 1, 1, tzinfo=timezone.utc)
    first = add_session(factory, title="Cũ", updated_at=base)
    second = add_session(factory, title="Mới A", updated_at=base + timedelta(days=1))
    third = add_session(factory, title="Mới B", updated_at=base + timedelta(days=1))
    response = client.get(
        "/chat/sessions?document_id=1&limit=2&offset=0",
        headers=authorization_header(42),
    )
    body = response.json()
    assert response.status_code == 200
    assert body["total"] == 3
    assert [item["id"] for item in body["items"]] == [third, second]
    assert first not in [item["id"] for item in body["items"]]
    assert all("content" not in item for item in body["items"])


def test_other_user_cannot_list_sessions_or_messages(
    chat_api_environment: tuple[
        TestClient, sessionmaker[Session], FakeRetrieval, FakeAnswer
    ],
) -> None:
    client, factory, _, _ = chat_api_environment
    add_document(factory, user_id=8)
    add_user(factory, 42)
    session_id = add_session(factory)
    assert client.get(
        "/chat/sessions?document_id=1",
        headers=authorization_header(42),
    ).status_code == 404
    assert client.get(
        f"/chat/sessions/{session_id}/messages",
        headers=authorization_header(42),
    ).status_code == 404


def test_messages_are_ordered_paginated_and_include_verified_citations(
    chat_api_environment: tuple[
        TestClient, sessionmaker[Session], FakeRetrieval, FakeAnswer
    ],
) -> None:
    client, factory, _, _ = chat_api_environment
    add_document(factory)
    session_id = add_session(factory)
    add_history(factory, session_id)
    response = client.get(
        f"/chat/sessions/{session_id}/messages?limit=10&offset=0",
        headers=authorization_header(42),
    )
    body = response.json()
    assert response.status_code == 200
    assert body["total"] == 2
    assert [item["sequence_no"] for item in body["items"]] == [0, 1]
    assert body["items"][0]["citations"] == []
    assert body["items"][1]["citations"] == [
        {
            "chunk_id": 101,
            "chunk_index": 0,
            "page_number": 1,
            "citation_order": 0,
        }
    ]


def test_cursor_history_under_limit_returns_chronological_page(
    chat_api_environment: tuple[
        TestClient, sessionmaker[Session], FakeRetrieval, FakeAnswer
    ],
) -> None:
    client, factory, _, _ = chat_api_environment
    add_document(factory)
    session_id = add_session(factory)
    add_message_range(factory, session_id, start=0, stop=12)

    response = client.get(
        f"/chat/sessions/{session_id}/messages/cursor",
        headers=authorization_header(42),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 12
    assert body["limit"] == 50
    assert body["has_more"] is False
    assert body["next_before_sequence_no"] is None
    assert [item["sequence_no"] for item in body["items"]] == list(range(12))


def test_cursor_history_pages_latest_messages_without_duplicates_or_gaps(
    chat_api_environment: tuple[
        TestClient, sessionmaker[Session], FakeRetrieval, FakeAnswer
    ],
) -> None:
    client, factory, _, _ = chat_api_environment
    add_document(factory)
    session_id = add_session(factory)
    add_message_range(
        factory,
        session_id,
        start=0,
        stop=120,
        cited_sequence_no=1,
    )
    headers = authorization_header(42)

    newest = client.get(
        f"/chat/sessions/{session_id}/messages/cursor",
        headers=headers,
    ).json()
    middle = client.get(
        f"/chat/sessions/{session_id}/messages/cursor"
        f"?before_sequence_no={newest['next_before_sequence_no']}",
        headers=headers,
    ).json()
    oldest = client.get(
        f"/chat/sessions/{session_id}/messages/cursor"
        f"?before_sequence_no={middle['next_before_sequence_no']}",
        headers=headers,
    ).json()

    assert [item["sequence_no"] for item in newest["items"]] == list(
        range(70, 120)
    )
    assert newest["has_more"] is True
    assert newest["next_before_sequence_no"] == 70
    assert [item["sequence_no"] for item in middle["items"]] == list(
        range(20, 70)
    )
    assert middle["next_before_sequence_no"] == 20
    assert [item["sequence_no"] for item in oldest["items"]] == list(range(20))
    assert oldest["has_more"] is False
    assert oldest["next_before_sequence_no"] is None

    combined = oldest["items"] + middle["items"] + newest["items"]
    sequence_numbers = [item["sequence_no"] for item in combined]
    assert sequence_numbers == list(range(120))
    assert len(sequence_numbers) == len(set(sequence_numbers))
    assert oldest["items"][1]["citations"] == [
        {
            "chunk_id": 101,
            "chunk_index": 0,
            "page_number": 1,
            "citation_order": 0,
        }
    ]


def test_cursor_is_stable_when_new_messages_arrive_between_pages(
    chat_api_environment: tuple[
        TestClient, sessionmaker[Session], FakeRetrieval, FakeAnswer
    ],
) -> None:
    client, factory, _, _ = chat_api_environment
    add_document(factory)
    session_id = add_session(factory)
    add_message_range(factory, session_id, start=0, stop=75)
    headers = authorization_header(42)

    first = client.get(
        f"/chat/sessions/{session_id}/messages/cursor?limit=50",
        headers=headers,
    ).json()
    add_message_range(factory, session_id, start=75, stop=77)
    second = client.get(
        f"/chat/sessions/{session_id}/messages/cursor?limit=50"
        f"&before_sequence_no={first['next_before_sequence_no']}",
        headers=headers,
    ).json()

    assert [item["sequence_no"] for item in first["items"]] == list(
        range(25, 75)
    )
    assert [item["sequence_no"] for item in second["items"]] == list(range(25))
    assert not (
        {item["id"] for item in first["items"]}
        & {item["id"] for item in second["items"]}
    )
    assert all(item["sequence_no"] < 25 for item in second["items"])


def test_cursor_history_enforces_ownership_tombstone_and_validation(
    chat_api_environment: tuple[
        TestClient, sessionmaker[Session], FakeRetrieval, FakeAnswer
    ],
) -> None:
    client, factory, _, _ = chat_api_environment
    add_document(factory, user_id=8)
    add_user(factory, 42)
    session_id = add_session(factory)
    url = f"/chat/sessions/{session_id}/messages/cursor"

    assert client.get(url, headers=authorization_header(42)).status_code == 404
    assert client.get(
        f"{url}?before_sequence_no=-1",
        headers=authorization_header(8),
    ).status_code == 422
    assert client.get(
        f"{url}?limit=51",
        headers=authorization_header(8),
    ).status_code == 422

    with factory() as db:
        db.add(
            DocumentDeletionJob(
                document_id=1,
                user_id=8,
                storage_key="users/8/document-1-private-storage-key",
                status="PENDING",
                current_step="VECTOR_CLEANUP",
                attempt_count=0,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
        db.commit()
    assert client.get(url, headers=authorization_header(8)).status_code == 404


def test_offset_history_contract_remains_unchanged(
    chat_api_environment: tuple[
        TestClient, sessionmaker[Session], FakeRetrieval, FakeAnswer
    ],
) -> None:
    client, factory, _, _ = chat_api_environment
    add_document(factory)
    session_id = add_session(factory)
    add_message_range(factory, session_id, start=0, stop=60)

    response = client.get(
        f"/chat/sessions/{session_id}/messages?limit=10&offset=10",
        headers=authorization_header(42),
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"session_id", "items", "total", "limit", "offset"}
    assert [item["sequence_no"] for item in body["items"]] == list(
        range(10, 20)
    )


def test_message_history_discards_citation_from_another_document(
    chat_api_environment: tuple[
        TestClient, sessionmaker[Session], FakeRetrieval, FakeAnswer
    ],
) -> None:
    client, factory, _, _ = chat_api_environment
    add_document(factory, document_id=1)
    add_document(factory, document_id=2)
    session_id = add_session(factory, document_id=1)
    with factory() as db:
        message = ChatMessage(
            session_id=session_id,
            sequence_no=0,
            role="ASSISTANT",
            content="Câu trả lời lỗi dữ liệu",
            created_at=datetime.now(timezone.utc),
        )
        db.add(message)
        db.flush()
        db.add(
            ChatCitation(
                message_id=message.id,
                document_chunk_id=201,
                citation_order=0,
                created_at=datetime.now(timezone.utc),
            )
        )
        db.commit()
    response = client.get(
        f"/chat/sessions/{session_id}/messages",
        headers=authorization_header(42),
    )
    assert response.status_code == 200
    assert response.json()["items"][0]["citations"] == []


def test_valid_citation_returns_original_postgresql_content(
    chat_api_environment: tuple[
        TestClient, sessionmaker[Session], FakeRetrieval, FakeAnswer
    ],
) -> None:
    client, factory, retrieval, answer = chat_api_environment
    add_document(factory)
    session_id = add_session(factory)
    add_history(factory, session_id)
    with factory() as db:
        message_id = db.scalar(
            select(ChatMessage.id).where(
                ChatMessage.session_id == session_id,
                ChatMessage.role == "ASSISTANT",
            )
        )

    response = client.get(
        f"/chat/citations/101?session_id={session_id}&message_id={message_id}",
        headers=authorization_header(42),
    )

    assert response.status_code == 200
    assert response.json() == {
        "chunk_id": 101,
        "document_id": 1,
        "chunk_index": 0,
        "content": "N\u1ed9i dung PostgreSQL",
        "page_number": 1,
        "citation_order": 0,
    }
    assert retrieval.calls == []
    assert answer.calls == []


def test_other_user_cannot_read_citation(
    chat_api_environment: tuple[
        TestClient, sessionmaker[Session], FakeRetrieval, FakeAnswer
    ],
) -> None:
    client, factory, _, _ = chat_api_environment
    add_document(factory, user_id=8)
    add_user(factory, 42)
    session_id = add_session(factory)
    add_history(factory, session_id)
    with factory() as db:
        message_id = db.scalar(
            select(ChatMessage.id).where(ChatMessage.role == "ASSISTANT")
        )

    response = client.get(
        f"/chat/citations/101?session_id={session_id}&message_id={message_id}",
        headers=authorization_header(42),
    )
    assert response.status_code == 404


def test_citation_rejects_wrong_session_or_message(
    chat_api_environment: tuple[
        TestClient, sessionmaker[Session], FakeRetrieval, FakeAnswer
    ],
) -> None:
    client, factory, _, _ = chat_api_environment
    add_document(factory)
    session_id = add_session(factory)
    other_session_id = add_session(factory)
    add_history(factory, session_id)
    with factory() as db:
        message_id = db.scalar(
            select(ChatMessage.id).where(ChatMessage.role == "ASSISTANT")
        )

    assert client.get(
        f"/chat/citations/101?session_id={other_session_id}&message_id={message_id}",
        headers=authorization_header(42),
    ).status_code == 404
    assert client.get(
        f"/chat/citations/101?session_id={session_id}&message_id={message_id + 999}",
        headers=authorization_header(42),
    ).status_code == 404


def test_chunk_must_be_linked_to_message_citation(
    chat_api_environment: tuple[
        TestClient, sessionmaker[Session], FakeRetrieval, FakeAnswer
    ],
) -> None:
    client, factory, _, _ = chat_api_environment
    add_document(factory)
    session_id = add_session(factory)
    add_history(factory, session_id)
    with factory() as db:
        message_id = db.scalar(
            select(ChatMessage.id).where(ChatMessage.role == "ASSISTANT")
        )
        content = "Doan khong duoc trich dan"
        db.add(DocumentChunk(
            id=102,
            document_id=1,
            chunk_index=1,
            content=content,
            start_char=20,
            end_char=20 + len(content),
            character_count=len(content),
            page_number=None,
            created_at=datetime.now(timezone.utc),
        ))
        db.commit()

    response = client.get(
        f"/chat/citations/102?session_id={session_id}&message_id={message_id}",
        headers=authorization_header(42),
    )
    assert response.status_code == 404


def test_citation_rejects_chunk_from_another_document(
    chat_api_environment: tuple[
        TestClient, sessionmaker[Session], FakeRetrieval, FakeAnswer
    ],
) -> None:
    client, factory, _, _ = chat_api_environment
    add_document(factory, document_id=1)
    add_document(factory, document_id=2)
    session_id = add_session(factory, document_id=1)
    with factory() as db:
        message = ChatMessage(
            session_id=session_id,
            sequence_no=0,
            role="ASSISTANT",
            content="Invalid cross-document citation",
            created_at=datetime.now(timezone.utc),
        )
        db.add(message)
        db.flush()
        db.add(ChatCitation(
            message_id=message.id,
            document_chunk_id=201,
            citation_order=0,
            created_at=datetime.now(timezone.utc),
        ))
        db.commit()
        message_id = message.id

    response = client.get(
        f"/chat/citations/201?session_id={session_id}&message_id={message_id}",
        headers=authorization_header(42),
    )
    assert response.status_code == 404


def test_citation_requires_assistant_message(
    chat_api_environment: tuple[
        TestClient, sessionmaker[Session], FakeRetrieval, FakeAnswer
    ],
) -> None:
    client, factory, _, _ = chat_api_environment
    add_document(factory)
    session_id = add_session(factory)
    with factory() as db:
        message = ChatMessage(
            session_id=session_id,
            sequence_no=0,
            role="USER",
            content="Invalid user citation",
            created_at=datetime.now(timezone.utc),
        )
        db.add(message)
        db.flush()
        db.add(ChatCitation(
            message_id=message.id,
            document_chunk_id=101,
            citation_order=0,
            created_at=datetime.now(timezone.utc),
        ))
        db.commit()
        message_id = message.id

    response = client.get(
        f"/chat/citations/101?session_id={session_id}&message_id={message_id}",
        headers=authorization_header(42),
    )
    assert response.status_code == 404


def test_history_gets_do_not_resolve_external_resources(
    chat_api_environment: tuple[
        TestClient, sessionmaker[Session], FakeRetrieval, FakeAnswer
    ],
) -> None:
    client, factory, _, _ = chat_api_environment
    add_document(factory)
    session_id = add_session(factory)

    def forbidden_resources() -> None:
        raise AssertionError("GET history must not initialize external providers")

    app.dependency_overrides[get_rag_chat_resources] = forbidden_resources
    assert client.get(
        "/chat/sessions?document_id=1",
        headers=authorization_header(42),
    ).status_code == 200
    assert client.get(
        f"/chat/sessions/{session_id}/messages",
        headers=authorization_header(42),
    ).status_code == 200


def test_message_history_has_bounded_query_count(
    chat_api_environment: tuple[
        TestClient, sessionmaker[Session], FakeRetrieval, FakeAnswer
    ],
) -> None:
    client, factory, _, _ = chat_api_environment
    add_document(factory)
    session_id = add_session(factory)
    add_history(factory, session_id)
    statements: list[str] = []
    engine = factory.kw["bind"]

    @event.listens_for(engine, "before_cursor_execute")
    def count_selects(
        connection: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    response = client.get(
        f"/chat/sessions/{session_id}/messages",
        headers=authorization_header(42),
    )
    assert response.status_code == 200
    # Auth user + ownership + count + one joined message/citation/chunk query.
    assert len(statements) <= 4


def test_success_response_does_not_expose_sensitive_fields(
    chat_api_environment: tuple[
        TestClient, sessionmaker[Session], FakeRetrieval, FakeAnswer
    ],
) -> None:
    client, factory, _, _ = chat_api_environment
    add_document(factory)
    response = client.post(
        "/chat/ask",
        headers=authorization_header(42),
        json={"document_id": 1, "question": "Q"},
    )
    assert response.status_code == 200
    assert "private-storage-key" not in response.text
    assert "api_key" not in response.text.lower()
    assert "storage_key" not in response.text.lower()


def test_chat_deadline_returns_safe_504_without_persisting_history(
    chat_api_environment: tuple[
        TestClient, sessionmaker[Session], FakeRetrieval, FakeAnswer
    ],
) -> None:
    client, factory, _, answer = chat_api_environment
    add_document(factory)

    class Clock:
        value = 0.0

        def __call__(self) -> float:
            return self.value

    clock = Clock()

    class ExpiringRetrieval(FakeRetrieval):
        def __call__(self, *args: object, **kwargs: object):
            result = super().__call__(*args, **kwargs)
            clock.value = 6
            return result

    app.dependency_overrides[get_rag_chat_resources] = lambda: RagChatResources(
        ExpiringRetrieval(),
        answer,
        deadline_seconds=5,
        clock=clock,
    )
    response = client.post(
        "/chat/ask",
        headers=authorization_header(42),
        json={"document_id": 1, "question": "secret-question-content"},
    )

    assert response.status_code == 504
    assert "quá thời gian" in response.json()["detail"]
    assert "secret-question-content" not in response.text
    with factory() as db:
        assert db.scalar(select(func.count(ChatSession.id))) == 0
        assert db.scalar(select(func.count(ChatMessage.id))) == 0
