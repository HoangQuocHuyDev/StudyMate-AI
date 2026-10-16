"""Tests for durable, owner-scoped document deletion and recovery."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event
from uuid import uuid4

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
from sqlalchemy.exc import SQLAlchemyError

from app.core.security import create_access_token
from app.db.session import get_db
from app.dependencies.rag import (
    DocumentDeletionResources,
    get_document_deletion_resources,
)
from app.main import app
from app.models.chat_citation import ChatCitation
from app.models.chat_message import ChatMessage
from app.models.chat_session import ChatSession
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.document_deletion_job import DocumentDeletionJob
from app.models.document_summary import DocumentSummary
from app.models.user import User
from app.routers.documents import get_file_storage
from app.services.document_deletion import (
    COMPLETED,
    DATABASE_DELETE,
    FAILED,
    FILE_CLEANUP,
    RUNNING,
    VECTOR_CLEANUP,
    DocumentDeletionConflictError,
    DocumentDeletionExternalError,
    DocumentDeletionInfrastructureError,
    DocumentDeletionNotFoundError,
    _advance_step,
    _claim_job,
    delete_owned_document,
    recover_document_deletions,
)
from app.services.document_processing import (
    DocumentNotFoundError,
    process_document,
)
from app.services.document_service import (
    OwnedDocumentNotFoundError,
    get_owned_document,
    list_documents,
)
from app.services.file_storage import StorageIOError
from app.services.rag.chat_history import (
    ChatHistoryNotFoundError,
    list_chat_sessions,
)
from app.services.rag.document_indexing import (
    DocumentIndexingNotFoundError,
    index_document,
)
from app.services.rag.document_retrieval import (
    DocumentRetrievalNotFoundError,
    retrieve_document_chunks,
)
from app.services.summary.document_summary import (
    SummaryDocumentNotFoundError,
    list_document_summaries,
)


class FakeVectorStore:
    def __init__(self) -> None:
        self.vectors: dict[tuple[int, int], set[str]] = {}
        self.delete_calls: list[tuple[int, int]] = []
        self.fail_delete = False
        self.fail_verify = False

    def delete_document_vectors(self, *, user_id: int, document_id: int) -> None:
        self.delete_calls.append((user_id, document_id))
        if self.fail_delete:
            raise RuntimeError("private chroma detail")
        self.vectors.pop((user_id, document_id), None)

    def get_document_vector_ids(
        self,
        *,
        user_id: int,
        document_id: int,
    ) -> set[str]:
        if self.fail_verify:
            raise RuntimeError("private chroma detail")
        return set(self.vectors.get((user_id, document_id), set()))


class FakeStorage:
    def __init__(self) -> None:
        self.files: set[str] = set()
        self.delete_calls: list[str] = []
        self.fail_delete = False

    def delete(self, storage_key: str) -> bool:
        self.delete_calls.append(storage_key)
        if self.fail_delete:
            raise StorageIOError("private filesystem detail")
        existed = storage_key in self.files
        self.files.discard(storage_key)
        return existed


@pytest.fixture
def deletion_environment(
    client: TestClient,
    tmp_path: Path,
) -> Iterator[
    tuple[
        TestClient,
        sessionmaker[Session],
        FakeVectorStore,
        FakeStorage,
    ]
]:
    database_path = tmp_path / "document-deletion.sqlite3"
    engine = create_engine(
        f"sqlite+pysqlite:///{database_path.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 5},
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
        ChatSession.__table__,
        ChatMessage.__table__,
        ChatCitation.__table__,
    ):
        table.to_metadata(metadata)
    metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    vector_store = FakeVectorStore()
    storage = FakeStorage()

    def override_database() -> Iterator[Session]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_database
    app.dependency_overrides[get_file_storage] = lambda: storage
    app.dependency_overrides[get_document_deletion_resources] = lambda: (
        DocumentDeletionResources(vector_store=vector_store)  # type: ignore[arg-type]
    )
    yield client, factory, vector_store, storage
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_file_storage, None)
    app.dependency_overrides.pop(get_document_deletion_resources, None)
    engine.dispose()


def add_user(factory: sessionmaker[Session], user_id: int) -> None:
    with factory() as session:
        session.add(
            User(
                id=user_id,
                full_name=f"User {user_id}",
                username=f"deletion_user_{user_id}",
                password_hash="test-only-hash",
                role="USER",
                is_active=True,
                token_version=0,
                created_at=datetime.now(timezone.utc),
            )
        )
        session.commit()


def add_document(
    factory: sessionmaker[Session],
    storage: FakeStorage,
    vector_store: FakeVectorStore,
    *,
    document_id: int,
    user_id: int,
    status: str = "READY",
    rag_status: str = "READY",
    with_relations: bool = False,
) -> str:
    storage_key = f"users/{user_id}/document-{document_id}"
    now = datetime.now(timezone.utc)
    with factory() as session:
        document = Document(
            id=document_id,
            user_id=user_id,
            title=f"Document {document_id}",
            original_filename=f"document-{document_id}.pdf",
            storage_key=storage_key,
            file_type="PDF",
            mime_type="application/pdf",
            file_size=100,
            status=status,
            rag_status=rag_status,
            created_at=now,
            updated_at=now,
        )
        session.add(document)
        session.flush()
        if with_relations:
            chunk = DocumentChunk(
                document_id=document_id,
                chunk_index=0,
                content="Ná»™i dung kiá»ƒm thá»­",
                start_char=0,
                end_char=18,
                character_count=18,
                page_number=1,
            )
            summary = DocumentSummary(
                document_id=document_id,
                summary_type="SHORT",
                content="TÃ³m táº¯t",
                model_name="fake-model",
            )
            chat_session = ChatSession(document_id=document_id, title="Há»i Ä‘Ã¡p")
            session.add_all((chunk, summary, chat_session))
            session.flush()
            message = ChatMessage(
                session_id=chat_session.id,
                sequence_no=0,
                role="ASSISTANT",
                content="CÃ¢u tráº£ lá»i",
            )
            session.add(message)
            session.flush()
            session.add(
                ChatCitation(
                    message_id=message.id,
                    document_chunk_id=chunk.id,
                    citation_order=0,
                )
            )
        session.commit()
    storage.files.add(storage_key)
    vector_store.vectors[(user_id, document_id)] = {
        f"document_chunk:{document_id}"
    }
    return storage_key


def auth(user_id: int) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id, 0)}"}


def test_success_deletes_all_related_data_and_preserves_other_user(
    deletion_environment: tuple[
        TestClient, sessionmaker[Session], FakeVectorStore, FakeStorage
    ],
) -> None:
    _, factory, vectors, storage = deletion_environment
    add_user(factory, 1)
    add_user(factory, 2)
    first_key = add_document(
        factory,
        storage,
        vectors,
        document_id=10,
        user_id=1,
        with_relations=True,
    )
    second_key = add_document(
        factory,
        storage,
        vectors,
        document_id=20,
        user_id=2,
        with_relations=True,
    )

    with factory() as session:
        result = delete_owned_document(
            session,
            vectors,
            storage,  # type: ignore[arg-type]
            document_id=10,
            user_id=1,
        )

    assert result.status == COMPLETED
    assert first_key not in storage.files
    assert second_key in storage.files
    assert (1, 10) not in vectors.vectors
    assert vectors.vectors[(2, 20)]
    with factory() as session:
        assert session.get(Document, 10) is None
        assert session.get(Document, 20) is not None
        assert session.scalar(select(func.count()).select_from(DocumentChunk)) == 1
        assert session.scalar(select(func.count()).select_from(DocumentSummary)) == 1
        assert session.scalar(select(func.count()).select_from(ChatSession)) == 1
        assert session.scalar(select(func.count()).select_from(ChatMessage)) == 1
        assert session.scalar(select(func.count()).select_from(ChatCitation)) == 1
        job = session.scalar(
            select(DocumentDeletionJob).where(
                DocumentDeletionJob.document_id == 10
            )
        )
        assert job is not None
        assert (job.status, job.current_step, job.storage_key) == (
            COMPLETED,
            "DONE",
            None,
        )


def test_owner_check_and_busy_document_conflicts(
    deletion_environment: tuple[
        TestClient, sessionmaker[Session], FakeVectorStore, FakeStorage
    ],
) -> None:
    _, factory, vectors, storage = deletion_environment
    add_user(factory, 1)
    add_user(factory, 2)
    add_document(factory, storage, vectors, document_id=1, user_id=1)
    add_document(
        factory,
        storage,
        vectors,
        document_id=2,
        user_id=1,
        status="PROCESSING",
        rag_status="PENDING",
    )
    add_document(
        factory,
        storage,
        vectors,
        document_id=3,
        user_id=1,
        rag_status="INDEXING",
    )

    with factory() as session, pytest.raises(DocumentDeletionNotFoundError):
        delete_owned_document(
            session,
            vectors,
            storage,  # type: ignore[arg-type]
            document_id=1,
            user_id=2,
        )
    for document_id in (2, 3):
        with factory() as session, pytest.raises(DocumentDeletionConflictError):
            delete_owned_document(
                session,
                vectors,
                storage,  # type: ignore[arg-type]
                document_id=document_id,
                user_id=1,
            )


def test_vector_failure_is_retryable_from_vector_step(
    deletion_environment: tuple[
        TestClient, sessionmaker[Session], FakeVectorStore, FakeStorage
    ],
) -> None:
    _, factory, vectors, storage = deletion_environment
    add_user(factory, 1)
    storage_key = add_document(
        factory, storage, vectors, document_id=1, user_id=1
    )
    vectors.fail_delete = True
    with factory() as session, pytest.raises(DocumentDeletionExternalError):
        delete_owned_document(
            session,
            vectors,
            storage,  # type: ignore[arg-type]
            document_id=1,
            user_id=1,
        )
    with factory() as session:
        job = session.scalar(select(DocumentDeletionJob))
        assert job is not None
        assert (job.status, job.current_step) == (FAILED, VECTOR_CLEANUP)
        assert job.lease_token is None
        assert session.get(Document, 1) is not None
    assert storage_key in storage.files

    vectors.fail_delete = False
    with factory() as session:
        delete_owned_document(
            session,
            vectors,
            storage,  # type: ignore[arg-type]
            document_id=1,
            user_id=1,
        )
    with factory() as session:
        job = session.scalar(select(DocumentDeletionJob))
        assert job is not None and job.status == COMPLETED
        assert job.attempt_count == 2


def test_file_failure_resumes_without_repeating_vector_cleanup(
    deletion_environment: tuple[
        TestClient, sessionmaker[Session], FakeVectorStore, FakeStorage
    ],
) -> None:
    _, factory, vectors, storage = deletion_environment
    add_user(factory, 1)
    add_document(factory, storage, vectors, document_id=1, user_id=1)
    storage.fail_delete = True
    with factory() as session, pytest.raises(DocumentDeletionExternalError):
        delete_owned_document(
            session,
            vectors,
            storage,  # type: ignore[arg-type]
            document_id=1,
            user_id=1,
        )
    with factory() as session:
        job = session.scalar(select(DocumentDeletionJob))
        assert job is not None
        assert (job.status, job.current_step) == (FAILED, FILE_CLEANUP)
    assert vectors.delete_calls == [(1, 1)]


def test_database_commit_failure_rolls_back_and_retries_database_step_only(
    deletion_environment: tuple[
        TestClient, sessionmaker[Session], FakeVectorStore, FakeStorage
    ],
) -> None:
    _, factory, vectors, storage = deletion_environment
    add_user(factory, 1)
    storage_key = add_document(
        factory, storage, vectors, document_id=1, user_id=1
    )

    class FailFinalCommitSession(Session):
        commit_count = 0

        def commit(self) -> None:
            self.commit_count += 1
            if self.commit_count == 5:
                raise SQLAlchemyError("test-only final commit failure")
            super().commit()

    failing_factory = sessionmaker(
        bind=factory.kw["bind"],
        class_=FailFinalCommitSession,
        expire_on_commit=False,
    )
    with failing_factory() as session, pytest.raises(
        DocumentDeletionInfrastructureError
    ):
        delete_owned_document(
            session,
            vectors,
            storage,  # type: ignore[arg-type]
            document_id=1,
            user_id=1,
        )

    with factory() as session:
        job = session.scalar(select(DocumentDeletionJob))
        assert job is not None
        assert (job.status, job.current_step, job.storage_key) == (
            FAILED,
            "DATABASE_DELETE",
            None,
        )
        assert job.last_error_code == "database_delete_failed"
        assert session.get(Document, 1) is not None
    assert storage_key not in storage.files
    assert (1, 1) not in vectors.vectors

    vector_call_count = len(vectors.delete_calls)
    file_call_count = len(storage.delete_calls)
    with factory() as session:
        result = delete_owned_document(
            session,
            vectors,
            storage,  # type: ignore[arg-type]
            document_id=1,
            user_id=1,
        )

    assert result.status == COMPLETED
    assert len(vectors.delete_calls) == vector_call_count
    assert len(storage.delete_calls) == file_call_count
    with factory() as session:
        assert session.get(Document, 1) is None
        job = session.scalar(select(DocumentDeletionJob))
        assert job is not None and job.status == COMPLETED

    storage.fail_delete = False
    with factory() as session:
        delete_owned_document(
            session,
            vectors,
            storage,  # type: ignore[arg-type]
            document_id=1,
            user_id=1,
        )
    assert vectors.delete_calls == [(1, 1)]


def test_expired_lease_is_reclaimed_and_live_lease_conflicts(
    deletion_environment: tuple[
        TestClient, sessionmaker[Session], FakeVectorStore, FakeStorage
    ],
) -> None:
    _, factory, vectors, storage = deletion_environment
    add_user(factory, 1)
    storage_key = add_document(
        factory, storage, vectors, document_id=1, user_id=1
    )
    with factory() as session:
        session.add(
            DocumentDeletionJob(
                document_id=1,
                user_id=1,
                storage_key=storage_key,
                status=RUNNING,
                current_step=VECTOR_CLEANUP,
                attempt_count=1,
                lease_token=uuid4(),
                lease_expires_at=datetime.now(timezone.utc)
                + timedelta(minutes=5),
            )
        )
        session.commit()
    with factory() as session, pytest.raises(DocumentDeletionConflictError):
        delete_owned_document(
            session,
            vectors,
            storage,  # type: ignore[arg-type]
            document_id=1,
            user_id=1,
        )
    with factory() as session:
        job = session.scalar(select(DocumentDeletionJob))
        assert job is not None
        job.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        session.commit()
    with factory() as session:
        delete_owned_document(
            session,
            vectors,
            storage,  # type: ignore[arg-type]
            document_id=1,
            user_id=1,
        )
    with factory() as session:
        job = session.scalar(select(DocumentDeletionJob))
        assert job is not None and job.status == COMPLETED
        assert job.attempt_count == 2


def test_explicit_recovery_sweep_continues_failed_job(
    deletion_environment: tuple[
        TestClient, sessionmaker[Session], FakeVectorStore, FakeStorage
    ],
) -> None:
    _, factory, vectors, storage = deletion_environment
    add_user(factory, 1)
    storage_key = add_document(
        factory, storage, vectors, document_id=1, user_id=1
    )
    with factory() as session:
        session.add(
            DocumentDeletionJob(
                document_id=1,
                user_id=1,
                storage_key=storage_key,
                status=FAILED,
                current_step=FILE_CLEANUP,
                attempt_count=1,
                last_error_code="file_cleanup_failed",
                last_error_at=datetime.now(timezone.utc),
            )
        )
        session.commit()

    result = recover_document_deletions(
        factory,
        vectors,
        storage,  # type: ignore[arg-type]
    )

    assert result.discovered == 1
    assert result.completed == 1
    assert vectors.delete_calls == []
    with factory() as session:
        assert session.get(Document, 1) is None


def test_reclaimed_lease_fences_the_previous_worker(
    deletion_environment: tuple[
        TestClient, sessionmaker[Session], FakeVectorStore, FakeStorage
    ],
) -> None:
    """A stale worker cannot advance a job after another worker reclaims it."""

    _, factory, vectors, storage = deletion_environment
    add_user(factory, 1)
    storage_key = add_document(
        factory, storage, vectors, document_id=1, user_id=1
    )
    stale_token = uuid4()
    with factory() as session:
        session.add(
            DocumentDeletionJob(
                document_id=1,
                user_id=1,
                storage_key=storage_key,
                status=RUNNING,
                current_step=VECTOR_CLEANUP,
                attempt_count=1,
                lease_token=stale_token,
                lease_expires_at=datetime.now(timezone.utc)
                - timedelta(seconds=1),
            )
        )
        session.commit()

    with factory() as session:
        current_token = _claim_job(
            session,
            document_id=1,
            user_id=1,
            lease_seconds=60,
        )

    assert current_token != stale_token
    with factory() as session, pytest.raises(DocumentDeletionConflictError):
        _advance_step(
            session,
            document_id=1,
            user_id=1,
            lease_token=stale_token,
            expected_step=VECTOR_CLEANUP,
            next_step=FILE_CLEANUP,
        )

    with factory() as session:
        job = session.scalar(select(DocumentDeletionJob))
        assert job is not None
        assert job.status == RUNNING
        assert job.current_step == VECTOR_CLEANUP
        assert job.lease_token == current_token
        assert job.attempt_count == 2
        assert session.get(Document, 1) is not None


def test_recovery_skips_live_lease_and_preserves_unrelated_document(
    deletion_environment: tuple[
        TestClient, sessionmaker[Session], FakeVectorStore, FakeStorage
    ],
) -> None:
    """A sweep only resumes claimable jobs and leaves other data untouched."""

    _, factory, vectors, storage = deletion_environment
    add_user(factory, 1)
    failed_key = add_document(
        factory, storage, vectors, document_id=1, user_id=1
    )
    live_key = add_document(
        factory, storage, vectors, document_id=2, user_id=1
    )
    unrelated_key = add_document(
        factory, storage, vectors, document_id=3, user_id=1
    )
    # FILE_CLEANUP means vector cleanup was already durably completed.
    vectors.vectors.pop((1, 1))
    with factory() as session:
        session.add_all(
            (
                DocumentDeletionJob(
                    document_id=1,
                    user_id=1,
                    storage_key=failed_key,
                    status=FAILED,
                    current_step=FILE_CLEANUP,
                    attempt_count=1,
                    last_error_code="file_cleanup_failed",
                    last_error_at=datetime.now(timezone.utc),
                ),
                DocumentDeletionJob(
                    document_id=2,
                    user_id=1,
                    storage_key=live_key,
                    status=RUNNING,
                    current_step=VECTOR_CLEANUP,
                    attempt_count=1,
                    lease_token=uuid4(),
                    lease_expires_at=datetime.now(timezone.utc)
                    + timedelta(minutes=5),
                ),
            )
        )
        session.commit()

    result = recover_document_deletions(
        factory,
        vectors,
        storage,  # type: ignore[arg-type]
    )

    assert (result.discovered, result.completed, result.failed) == (1, 1, 0)
    with factory() as session:
        assert session.get(Document, 1) is None
        assert session.get(Document, 2) is not None
        assert session.get(Document, 3) is not None
        live_job = session.scalar(
            select(DocumentDeletionJob).where(
                DocumentDeletionJob.document_id == 2
            )
        )
        assert live_job is not None and live_job.status == RUNNING
    assert live_key in storage.files
    assert unrelated_key in storage.files
    assert vectors.vectors[(1, 2)]
    assert vectors.vectors[(1, 3)]


def test_vector_verification_failure_is_retryable(
    deletion_environment: tuple[
        TestClient, sessionmaker[Session], FakeVectorStore, FakeStorage
    ],
) -> None:
    """Failure to verify Chroma cleanup remains at the idempotent vector step."""

    _, factory, vectors, storage = deletion_environment
    add_user(factory, 1)
    storage_key = add_document(
        factory, storage, vectors, document_id=1, user_id=1
    )
    vectors.fail_verify = True

    with factory() as session, pytest.raises(DocumentDeletionExternalError):
        delete_owned_document(
            session,
            vectors,
            storage,  # type: ignore[arg-type]
            document_id=1,
            user_id=1,
        )

    with factory() as session:
        job = session.scalar(select(DocumentDeletionJob))
        assert job is not None
        assert (job.status, job.current_step) == (FAILED, VECTOR_CLEANUP)
        assert session.get(Document, 1) is not None
    assert storage_key in storage.files

    vectors.fail_verify = False
    with factory() as session:
        delete_owned_document(
            session,
            vectors,
            storage,  # type: ignore[arg-type]
            document_id=1,
            user_id=1,
        )

    assert vectors.delete_calls == [(1, 1), (1, 1)]
    with factory() as session:
        assert session.get(Document, 1) is None
        job = session.scalar(select(DocumentDeletionJob))
        assert job is not None and job.status == COMPLETED


def test_delete_api_statuses_and_idempotent_completed_request(
    deletion_environment: tuple[
        TestClient, sessionmaker[Session], FakeVectorStore, FakeStorage
    ],
) -> None:
    client, factory, vectors, storage = deletion_environment
    add_user(factory, 1)
    add_user(factory, 2)
    add_document(factory, storage, vectors, document_id=1, user_id=1)
    add_document(
        factory,
        storage,
        vectors,
        document_id=2,
        user_id=1,
        status="PROCESSING",
        rag_status="PENDING",
    )

    assert client.delete("/documents/1").status_code == 401
    assert client.delete("/documents/1", headers=auth(2)).status_code == 404
    assert client.delete("/documents/2", headers=auth(1)).status_code == 409
    response = client.delete("/documents/1", headers=auth(1))
    assert response.status_code == 204
    assert response.content == b""
    assert client.delete("/documents/1", headers=auth(1)).status_code == 204


def test_delete_api_maps_external_failure_without_leaking_details(
    deletion_environment: tuple[
        TestClient, sessionmaker[Session], FakeVectorStore, FakeStorage
    ],
) -> None:
    client, factory, vectors, storage = deletion_environment
    add_user(factory, 1)
    add_document(factory, storage, vectors, document_id=1, user_id=1)
    vectors.fail_delete = True

    response = client.delete("/documents/1", headers=auth(1))

    assert response.status_code == 503
    serialized = response.text.lower()
    assert "private" not in serialized
    assert "storage_key" not in serialized


def test_second_worker_is_rejected_while_first_holds_live_lease(
    deletion_environment: tuple[
        TestClient, sessionmaker[Session], FakeVectorStore, FakeStorage
    ],
) -> None:
    _, factory, vectors, storage = deletion_environment
    add_user(factory, 1)
    add_document(factory, storage, vectors, document_id=1, user_id=1)
    entered = Event()
    release = Event()

    class BlockingVectorStore(FakeVectorStore):
        def delete_document_vectors(
            self,
            *,
            user_id: int,
            document_id: int,
        ) -> None:
            entered.set()
            assert release.wait(timeout=5)
            super().delete_document_vectors(
                user_id=user_id,
                document_id=document_id,
            )

    blocking = BlockingVectorStore()
    blocking.vectors = vectors.vectors
    from concurrent.futures import ThreadPoolExecutor

    def first_worker() -> str:
        with factory() as session:
            delete_owned_document(
                session,
                blocking,
                storage,  # type: ignore[arg-type]
                document_id=1,
                user_id=1,
            )
        return "completed"

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(first_worker)
        assert entered.wait(timeout=5)
        with factory() as session, pytest.raises(DocumentDeletionConflictError):
            delete_owned_document(
                session,
                vectors,
                storage,  # type: ignore[arg-type]
                document_id=1,
                user_id=1,
            )
        release.set()
        assert future.result(timeout=5) == "completed"


def test_active_job_tombstones_all_new_document_operations(
    deletion_environment: tuple[
        TestClient, sessionmaker[Session], FakeVectorStore, FakeStorage
    ],
) -> None:
    _, factory, vectors, storage = deletion_environment
    add_user(factory, 1)
    storage_key = add_document(
        factory,
        storage,
        vectors,
        document_id=1,
        user_id=1,
        status="UPLOADED",
        rag_status="PENDING",
    )
    with factory() as session:
        session.add(
            DocumentDeletionJob(
                document_id=1,
                user_id=1,
                storage_key=storage_key,
            )
        )
        session.commit()

    class ForbiddenEmbedder:
        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            raise AssertionError("Embedding must not run for a tombstoned document")

        def embed_query(self, query: str) -> list[float]:
            raise AssertionError("Embedding must not run for a tombstoned document")

    with factory() as session:
        result = list_documents(session, user_id=1, page=1, page_size=10)
        assert result.items == []
        with pytest.raises(OwnedDocumentNotFoundError):
            get_owned_document(session, document_id=1, user_id=1)
        with pytest.raises(DocumentNotFoundError):
            process_document(
                session,
                storage,  # type: ignore[arg-type]
                document_id=1,
                user_id=1,
            )
        with pytest.raises(DocumentIndexingNotFoundError):
            index_document(
                session,
                ForbiddenEmbedder(),
                vectors,
                document_id=1,
                user_id=1,
            )
        with pytest.raises(DocumentRetrievalNotFoundError):
            retrieve_document_chunks(
                session,
                ForbiddenEmbedder(),
                vectors,
                document_id=1,
                user_id=1,
                query="CÃ¢u há»i",
            )
        with pytest.raises(SummaryDocumentNotFoundError):
            list_document_summaries(session, document_id=1, user_id=1)
        with pytest.raises(ChatHistoryNotFoundError):
            list_chat_sessions(
                session,
                document_id=1,
                user_id=1,
                limit=20,
                offset=0,
            )


@pytest.mark.skip(
    reason="No verified isolated PostgreSQL test database is configured.",
)
def test_postgresql_row_lock_and_cascade_integration() -> None:
    """Reserved for a dedicated disposable PostgreSQL integration target."""

