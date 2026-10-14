"""Tests for transactional RAG chat history orchestration."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
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
    func,
    select,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.models.chat_citation import ChatCitation
from app.models.chat_message import ChatMessage
from app.models.chat_session import ChatSession
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.document_deletion_job import DocumentDeletionJob
from app.models.user import User
from app.services.rag.answer_service import (
    GeminiAnswerTimeoutError,
    GeneratedAnswer,
    LOCAL_GROUNDING_MODEL,
    NO_CONTEXT_ANSWER,
    UNVERIFIED_GROUNDING_ANSWER,
)
from app.services.rag.chat_service import (
    ChatAnswerError,
    ChatCapacityLimitError,
    ChatConcurrencyError,
    ChatCoordinationError,
    ChatDeadlineExceededError,
    ChatDocumentNotFoundError,
    ChatDocumentNotReadyError,
    ChatPersistenceError,
    ChatRetrievalError,
    ChatSessionNotFoundError,
    InvalidChatCitationError,
    InvalidChatRequestError,
    _session_for_update_statement,
    ask_document,
)
from app.services.summary.concurrency import (
    SummaryConcurrencyError,
    SummaryConcurrencyLimitError,
)
from app.services.rag.document_retrieval import (
    DocumentVectorSearchError,
    RetrievedDocumentChunk,
)


@pytest.fixture
def chat_database(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'chat.sqlite3'}",
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
    yield factory
    engine.dispose()


class FakeRetrieval:
    def __init__(
        self,
        chunks: Sequence[RetrievedDocumentChunk] = (),
        *,
        error: Exception | None = None,
    ) -> None:
        self.chunks = list(chunks)
        self.error = error
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
        return list(self.chunks)


class FakeAnswer:
    def __init__(
        self,
        answer: GeneratedAnswer | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.answer = answer or GeneratedAnswer(
            answer_text="Câu trả lời [Nguồn 1]",
            cited_chunk_ids=[101],
            model_name="fake-gemini",
        )
        self.error = error
        self.calls: list[tuple[str, tuple[RetrievedDocumentChunk, ...]]] = []
        self.timeouts: list[float | None] = []

    def generate_answer(
        self,
        question: str,
        retrieved_chunks: Sequence[RetrievedDocumentChunk],
        *,
        timeout_seconds: float | None = None,
    ) -> GeneratedAnswer:
        self.calls.append((question, tuple(retrieved_chunks)))
        self.timeouts.append(timeout_seconds)
        if self.error is not None:
            raise self.error
        return self.answer


def add_ready_document(
    factory: sessionmaker[Session],
    *,
    document_id: int = 1,
    user_id: int = 7,
    status: str = "READY",
    rag_status: str = "READY",
) -> None:
    now = datetime.now(timezone.utc)
    with factory.begin() as db:
        if db.get(User, user_id) is None:
            db.add(
                User(
                    id=user_id,
                    full_name=f"User {user_id}",
                    username=f"user_{user_id}",
                    password_hash="test-hash",
                    role="USER",
                    is_active=True,
                    created_at=now,
                )
            )
            db.flush()
        document = Document(
                id=document_id,
                user_id=user_id,
                title=f"Document {document_id}",
                original_filename="document.docx",
                storage_key=f"users/{user_id}/document-{document_id}",
                file_type="DOCX",
                mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                file_size=100,
                status=status,
                rag_status=rag_status,
                created_at=now,
                updated_at=now,
            )
        db.add(document)
        db.flush()
        db.add_all(
            [
                DocumentChunk(
                    id=document_id * 100 + 1,
                    document_id=document_id,
                    chunk_index=0,
                    content="Nội dung một",
                    start_char=0,
                    end_char=12,
                    character_count=12,
                    page_number=1,
                    created_at=now,
                ),
                DocumentChunk(
                    id=document_id * 100 + 2,
                    document_id=document_id,
                    chunk_index=1,
                    content="Nội dung hai",
                    start_char=12,
                    end_char=24,
                    character_count=12,
                    page_number=None,
                    created_at=now,
                ),
            ]
        )


def chunks(document_id: int = 1) -> list[RetrievedDocumentChunk]:
    return [
        RetrievedDocumentChunk(101, document_id, 0, "Nội dung một", 1, 0.1),
        RetrievedDocumentChunk(102, document_id, 1, "Nội dung hai", None, 0.2),
    ]


def create_session(factory: sessionmaker[Session], document_id: int = 1) -> int:
    now = datetime.now(timezone.utc)
    with factory.begin() as db:
        chat_session = ChatSession(
            document_id=document_id,
            title="Phiên cũ",
            created_at=now,
            updated_at=now,
        )
        db.add(chat_session)
        db.flush()
        return chat_session.id


def ask(
    factory: sessionmaker[Session],
    retrieval: FakeRetrieval | None = None,
    answer: FakeAnswer | None = None,
    **kwargs: object,
):
    with factory() as db:
        return ask_document(
            db,
            retrieval or FakeRetrieval(chunks()),
            answer or FakeAnswer(),
            document_id=kwargs.pop("document_id", 1),
            user_id=kwargs.pop("user_id", 7),
            question=kwargs.pop("question", "  Trí tuệ nhân tạo là gì?  "),
            session_id=kwargs.pop("session_id", None),
            **kwargs,
        )


def test_new_session_persists_complete_turn(
    chat_database: sessionmaker[Session],
) -> None:
    add_ready_document(chat_database)

    result = ask(chat_database)

    with chat_database() as db:
        session = db.get(ChatSession, result.session_id)
        messages = db.scalars(
            select(ChatMessage)
            .where(ChatMessage.session_id == result.session_id)
            .order_by(ChatMessage.sequence_no)
        ).all()
        citations = db.scalars(select(ChatCitation)).all()
        assert session is not None
        assert session.title == "Trí tuệ nhân tạo là gì?"
        assert [(item.sequence_no, item.role) for item in messages] == [
            (0, "USER"),
            (1, "ASSISTANT"),
        ]
        assert citations[0].message_id == result.assistant_message_id
        assert result.citations[0].chunk_id == 101
        assert result.citations[0].citation_order == 0


def test_existing_session_appends_consecutive_messages(
    chat_database: sessionmaker[Session],
) -> None:
    add_ready_document(chat_database)
    session_id = create_session(chat_database)
    first = ask(chat_database, session_id=session_id)
    second = ask(chat_database, session_id=session_id, question="Câu tiếp theo")

    with chat_database() as db:
        sequence = db.scalars(
            select(ChatMessage.sequence_no)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.sequence_no)
        ).all()
    assert first.session_id == second.session_id == session_id
    assert sequence == [0, 1, 2, 3]


def test_existing_session_updated_at_is_refreshed(
    chat_database: sessionmaker[Session],
) -> None:
    add_ready_document(chat_database)
    session_id = create_session(chat_database)
    old_timestamp = datetime(2000, 1, 1, tzinfo=timezone.utc)
    with chat_database.begin() as db:
        chat_session = db.get(ChatSession, session_id)
        assert chat_session is not None
        chat_session.updated_at = old_timestamp

    ask(chat_database, session_id=session_id)

    with chat_database() as db:
        chat_session = db.get(ChatSession, session_id)
        assert chat_session is not None
        assert chat_session.updated_at != old_timestamp


def test_valid_owner_is_forwarded_to_retrieval(
    chat_database: sessionmaker[Session],
) -> None:
    add_ready_document(chat_database)
    retrieval = FakeRetrieval(chunks())
    ask(chat_database, retrieval=retrieval)
    assert retrieval.calls == [
        {"document_id": 1, "user_id": 7, "query": "Trí tuệ nhân tạo là gì?"}
    ]


def test_other_user_is_rejected_before_providers(
    chat_database: sessionmaker[Session],
) -> None:
    add_ready_document(chat_database)
    retrieval = FakeRetrieval(chunks())
    with pytest.raises(ChatDocumentNotFoundError):
        ask(chat_database, retrieval=retrieval, user_id=8)
    assert retrieval.calls == []


def test_session_for_another_document_is_rejected(
    chat_database: sessionmaker[Session],
) -> None:
    add_ready_document(chat_database)
    add_ready_document(chat_database, document_id=2)
    session_id = create_session(chat_database, document_id=2)
    with pytest.raises(ChatSessionNotFoundError):
        ask(chat_database, session_id=session_id)


@pytest.mark.parametrize(
    ("status", "rag_status"),
    [("UPLOADED", "READY"), ("PROCESSING", "READY"), ("READY", "PENDING")],
)
def test_document_must_be_ready_for_rag(
    chat_database: sessionmaker[Session],
    status: str,
    rag_status: str,
) -> None:
    add_ready_document(chat_database, status=status, rag_status=rag_status)
    with pytest.raises(ChatDocumentNotReadyError):
        ask(chat_database)


def test_citations_are_ordered_and_only_link_to_assistant(
    chat_database: sessionmaker[Session],
) -> None:
    add_ready_document(chat_database)
    answer = FakeAnswer(
        GeneratedAnswer("Hai nguồn", [102, 101], "fake-gemini")
    )
    result = ask(chat_database, answer=answer)
    with chat_database() as db:
        citations = db.scalars(
            select(ChatCitation).order_by(ChatCitation.citation_order)
        ).all()
    assert [(c.document_chunk_id, c.citation_order) for c in citations] == [
        (102, 0),
        (101, 1),
    ]
    assert all(c.message_id == result.assistant_message_id for c in citations)
    assert [(c.chunk_index, c.page_number) for c in result.citations] == [
        (1, None),
        (0, 1),
    ]


@pytest.mark.parametrize("cited_ids", [[999], [101, 101], [102, 999]])
def test_fake_or_duplicate_citations_use_safe_fallback(
    chat_database: sessionmaker[Session],
    cited_ids: list[int],
) -> None:
    add_ready_document(chat_database)
    answer = FakeAnswer(GeneratedAnswer("Invalid", cited_ids, "fake-gemini"))
    result = ask(chat_database, answer=answer)
    assert result.answer_text == UNVERIFIED_GROUNDING_ANSWER
    assert result.citations == []
    assert table_counts(chat_database) == (1, 2, 0)


def test_citation_from_another_document_uses_safe_fallback(
    chat_database: sessionmaker[Session],
) -> None:
    add_ready_document(chat_database)
    add_ready_document(chat_database, document_id=2)

    result = ask(
        chat_database,
        answer=FakeAnswer(GeneratedAnswer("Invalid", [201], "fake-gemini")),
    )

    assert result.answer_text == UNVERIFIED_GROUNDING_ANSWER
    assert result.citations == []
    assert table_counts(chat_database) == (1, 2, 0)


def test_answer_cannot_cite_a_chunk_filtered_out_by_retrieval(
    chat_database: sessionmaker[Session],
) -> None:
    add_ready_document(chat_database)
    only_relevant_chunk = [chunks()[0]]

    result = ask(
        chat_database,
        retrieval=FakeRetrieval(only_relevant_chunk),
        answer=FakeAnswer(
            GeneratedAnswer("Nguồn đã bị lọc", [102], "fake-gemini")
        ),
    )

    assert result.answer_text == UNVERIFIED_GROUNDING_ANSWER
    assert result.citations == []
    assert table_counts(chat_database) == (1, 2, 0)


def test_retrieved_chunk_from_another_document_is_rejected(
    chat_database: sessionmaker[Session],
) -> None:
    add_ready_document(chat_database)
    retrieval = FakeRetrieval(chunks(document_id=2))
    with pytest.raises(ChatRetrievalError):
        ask(chat_database, retrieval=retrieval)
    assert table_counts(chat_database) == (0, 0, 0)


def test_answer_without_citations_is_replaced_before_persistence(
    chat_database: sessionmaker[Session],
) -> None:
    add_ready_document(chat_database)
    result = ask(
        chat_database,
        answer=FakeAnswer(GeneratedAnswer("Không đủ dữ liệu", [], "fake-gemini")),
    )
    assert result.answer_text == UNVERIFIED_GROUNDING_ANSWER
    assert result.model_name == LOCAL_GROUNDING_MODEL
    assert result.citations == []
    with chat_database() as db:
        persisted = db.scalar(
            select(ChatMessage.content).where(ChatMessage.role == "ASSISTANT")
        )
    assert persisted == UNVERIFIED_GROUNDING_ANSWER
    assert table_counts(chat_database) == (1, 2, 0)


def test_gemini_insufficient_information_answer_remains_distinct(
    chat_database: sessionmaker[Session],
) -> None:
    add_ready_document(chat_database)

    result = ask(
        chat_database,
        answer=FakeAnswer(
            GeneratedAnswer(NO_CONTEXT_ANSWER, [], "fake-gemini")
        ),
    )

    assert result.answer_text == NO_CONTEXT_ANSWER
    assert result.citations == []
    assert table_counts(chat_database) == (1, 2, 0)


def test_empty_retrieval_skips_gemini_and_persists_local_no_context_answer(
    chat_database: sessionmaker[Session],
) -> None:
    add_ready_document(chat_database)
    answer = FakeAnswer()

    result = ask(
        chat_database,
        retrieval=FakeRetrieval([]),
        answer=answer,
    )

    assert answer.calls == []
    assert result.answer_text == NO_CONTEXT_ANSWER
    assert result.model_name == LOCAL_GROUNDING_MODEL
    assert result.citations == []
    assert table_counts(chat_database) == (1, 2, 0)


def test_citation_removed_after_retrieval_rolls_back_the_whole_turn(
    chat_database: sessionmaker[Session],
) -> None:
    add_ready_document(chat_database)

    class RemovingChunkAnswer(FakeAnswer):
        def generate_answer(
            self,
            question: str,
            retrieved_chunks: Sequence[RetrievedDocumentChunk],
            *,
            timeout_seconds: float | None = None,
        ) -> GeneratedAnswer:
            with chat_database.begin() as other:
                chunk = other.get(DocumentChunk, 101)
                assert chunk is not None
                other.delete(chunk)
            return GeneratedAnswer("Trả lời [Nguồn 1]", [101], "fake-gemini")

    with pytest.raises(InvalidChatCitationError):
        ask(chat_database, answer=RemovingChunkAnswer())

    assert table_counts(chat_database) == (0, 0, 0)


def test_malformed_answer_is_rejected_safely_without_writes(
    chat_database: sessionmaker[Session],
) -> None:
    add_ready_document(chat_database)
    malformed = GeneratedAnswer(  # type: ignore[arg-type]
        answer_text=None,
        cited_chunk_ids=[],
        model_name="fake-gemini",
    )
    with pytest.raises(ChatAnswerError):
        ask(chat_database, answer=FakeAnswer(malformed))
    assert table_counts(chat_database) == (0, 0, 0)


@pytest.mark.parametrize(
    ("stage", "expected"),
    [("retrieval", ChatRetrievalError), ("answer", ChatAnswerError)],
)
def test_provider_failure_creates_no_empty_session_or_messages(
    chat_database: sessionmaker[Session],
    stage: str,
    expected: type[Exception],
) -> None:
    add_ready_document(chat_database)
    retrieval = FakeRetrieval(
        chunks(),
        error=DocumentVectorSearchError("secret path") if stage == "retrieval" else None,
    )
    answer = FakeAnswer(error=RuntimeError("secret-api-key")) if stage == "answer" else FakeAnswer()
    with pytest.raises(expected) as captured:
        ask(chat_database, retrieval=retrieval, answer=answer)
    assert "secret" not in str(captured.value).lower()
    assert table_counts(chat_database) == (0, 0, 0)


def test_tombstone_created_during_answer_generation_prevents_chat_write(
    chat_database: sessionmaker[Session],
) -> None:
    add_ready_document(chat_database)

    class TombstoningAnswer(FakeAnswer):
        def generate_answer(
            self,
            question: str,
            retrieved_chunks: Sequence[RetrievedDocumentChunk],
            *,
            timeout_seconds: float | None = None,
        ) -> GeneratedAnswer:
            with chat_database() as other:
                document = other.get(Document, 1)
                assert document is not None
                other.add(
                    DocumentDeletionJob(
                        document_id=1,
                        user_id=7,
                        storage_key=document.storage_key,
                    )
                )
                other.commit()
            return super().generate_answer(question, retrieved_chunks)

    with pytest.raises(ChatDocumentNotFoundError):
        ask(
            chat_database,
            retrieval=FakeRetrieval(chunks()),
            answer=TombstoningAnswer(),
        )
    assert table_counts(chat_database) == (0, 0, 0)


def test_no_database_transaction_is_open_during_both_providers(
    chat_database: sessionmaker[Session],
) -> None:
    add_ready_document(chat_database)
    class TransactionCheckingRetrieval(FakeRetrieval):
        def __call__(self, db: Session, **kwargs: object):
            assert not db.in_transaction()
            results = super().__call__(db, **kwargs)
            db.execute(select(Document.id)).first()
            return results

    with chat_database() as db:
        class TransactionCheckingAnswer(FakeAnswer):
            def generate_answer(
                self,
                question: str,
                retrieved_chunks: Sequence[RetrievedDocumentChunk],
                *,
                timeout_seconds: float | None = None,
            ) -> GeneratedAnswer:
                assert not db.in_transaction()
                return super().generate_answer(question, retrieved_chunks)

        ask_document(
            db,
            TransactionCheckingRetrieval(chunks()),
            TransactionCheckingAnswer(),
            document_id=1,
            user_id=7,
            question="Câu hỏi",
        )


def test_database_failure_rolls_back_new_session_messages_and_citations(
    chat_database: sessionmaker[Session],
) -> None:
    add_ready_document(chat_database)
    with chat_database() as db:
        @event.listens_for(db.bind, "before_cursor_execute")
        def fail_citation_insert(
            connection: object,
            cursor: object,
            statement: str,
            parameters: object,
            context: object,
            executemany: bool,
        ) -> None:
            if statement.lstrip().upper().startswith("INSERT INTO CHAT_CITATIONS"):
                raise SQLAlchemyError("sensitive database details")

        with pytest.raises(ChatPersistenceError) as captured:
            ask_document(
                db,
                FakeRetrieval(chunks()),
                FakeAnswer(),
                document_id=1,
                user_id=7,
                question="Câu hỏi",
            )
        assert "sensitive" not in str(captured.value).lower()
    assert table_counts(chat_database) == (0, 0, 0)


def test_integrity_conflict_is_mapped_and_rolled_back(
    chat_database: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    add_ready_document(chat_database)
    session_id = create_session(chat_database)
    with chat_database() as db:
        original_flush = db.flush
        def conflicting_flush(*args: object, **kwargs: object) -> None:
            if any(isinstance(item, ChatMessage) for item in db.new):
                raise IntegrityError("statement", {}, Exception("unique detail"))
            original_flush(*args, **kwargs)

        monkeypatch.setattr(db, "flush", conflicting_flush)
        with pytest.raises(ChatConcurrencyError) as captured:
            ask_document(
                db,
                FakeRetrieval(chunks()),
                FakeAnswer(),
                document_id=1,
                user_id=7,
                question="Câu hỏi",
                session_id=session_id,
            )
    assert "unique" not in str(captured.value).lower()
    assert table_counts(chat_database) == (1, 0, 0)


def test_postgresql_session_query_uses_row_lock() -> None:
    sql = str(
        _session_for_update_statement(1).compile(dialect=postgresql.dialect())
    ).upper()
    assert "FOR UPDATE" in sql


class RejectingCapacityCoordinator:
    def __init__(self, error: Exception) -> None:
        self.error = error
        self.calls = 0

    @contextmanager
    def capacity(self, user_id: int) -> Iterator[None]:
        assert user_id == 7
        self.calls += 1
        raise self.error
        yield


class TrackingCapacityCoordinator:
    def __init__(self) -> None:
        self.active = 0
        self.releases = 0

    @contextmanager
    def capacity(self, user_id: int) -> Iterator[None]:
        assert user_id == 7
        self.active += 1
        try:
            yield
        finally:
            self.active -= 1
            self.releases += 1


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class AdvancingAnswer(FakeAnswer):
    def __init__(self, clock: FakeClock, seconds: float) -> None:
        super().__init__()
        self.clock = clock
        self.seconds = seconds

    def generate_answer(
        self,
        question: str,
        retrieved_chunks: Sequence[RetrievedDocumentChunk],
        *,
        timeout_seconds: float | None = None,
    ) -> GeneratedAnswer:
        self.clock.advance(self.seconds)
        return super().generate_answer(
            question,
            retrieved_chunks,
            timeout_seconds=timeout_seconds,
        )


class AdvancingReleaseCoordinator(TrackingCapacityCoordinator):
    def __init__(self, clock: FakeClock, seconds: float) -> None:
        super().__init__()
        self.clock = clock
        self.seconds = seconds

    @contextmanager
    def capacity(self, user_id: int) -> Iterator[None]:
        with super().capacity(user_id):
            yield
        self.clock.advance(self.seconds)


def test_capacity_limit_prevents_provider_calls_and_history_writes(
    chat_database: sessionmaker[Session],
) -> None:
    add_ready_document(chat_database)
    retrieval = FakeRetrieval(chunks())
    answer = FakeAnswer()
    coordinator = RejectingCapacityCoordinator(
        SummaryConcurrencyLimitError("capacity exhausted")
    )

    with pytest.raises(ChatCapacityLimitError):
        ask(
            chat_database,
            retrieval=retrieval,
            answer=answer,
            concurrency_coordinator=coordinator,
        )

    assert coordinator.calls == 1
    assert retrieval.calls == []
    assert answer.calls == []
    assert table_counts(chat_database) == (0, 0, 0)


def test_coordination_failure_is_safe_and_creates_no_history(
    chat_database: sessionmaker[Session],
) -> None:
    add_ready_document(chat_database)
    coordinator = RejectingCapacityCoordinator(
        SummaryConcurrencyError("sensitive database detail")
    )

    with pytest.raises(ChatCoordinationError) as captured:
        ask(chat_database, concurrency_coordinator=coordinator)

    assert "sensitive" not in str(captured.value).lower()
    assert table_counts(chat_database) == (0, 0, 0)


def test_provider_failure_releases_capacity_and_retry_can_succeed(
    chat_database: sessionmaker[Session],
) -> None:
    add_ready_document(chat_database)
    coordinator = TrackingCapacityCoordinator()

    with pytest.raises(ChatAnswerError):
        ask(
            chat_database,
            answer=FakeAnswer(error=GeminiAnswerTimeoutError("provider timed out")),
            concurrency_coordinator=coordinator,
        )

    assert coordinator.active == 0
    assert coordinator.releases == 1
    result = ask(chat_database, concurrency_coordinator=coordinator)
    assert result.answer_text
    assert coordinator.active == 0
    assert coordinator.releases == 2
    assert table_counts(chat_database) == (1, 2, 1)


def test_answer_timeout_is_capped_by_remaining_deadline(
    chat_database: sessionmaker[Session],
) -> None:
    add_ready_document(chat_database)
    clock = FakeClock()
    answer = FakeAnswer()

    ask(
        chat_database,
        answer=answer,
        deadline_seconds=12,
        clock=clock,
    )

    assert len(answer.timeouts) == 1
    assert answer.timeouts[0] == pytest.approx(12)


def test_deadline_during_answer_releases_capacity_without_history(
    chat_database: sessionmaker[Session],
) -> None:
    add_ready_document(chat_database)
    clock = FakeClock()
    coordinator = TrackingCapacityCoordinator()

    with pytest.raises(ChatDeadlineExceededError):
        ask(
            chat_database,
            answer=AdvancingAnswer(clock, 6),
            concurrency_coordinator=coordinator,
            deadline_seconds=5,
            clock=clock,
        )

    assert coordinator.active == 0
    assert coordinator.releases == 1
    assert table_counts(chat_database) == (0, 0, 0)


def test_deadline_before_persistence_creates_no_history(
    chat_database: sessionmaker[Session],
) -> None:
    add_ready_document(chat_database)
    clock = FakeClock()
    coordinator = AdvancingReleaseCoordinator(clock, 6)

    with pytest.raises(ChatDeadlineExceededError):
        ask(
            chat_database,
            concurrency_coordinator=coordinator,
            deadline_seconds=5,
            clock=clock,
        )

    assert coordinator.active == 0
    assert coordinator.releases == 1
    assert table_counts(chat_database) == (0, 0, 0)


def test_deadline_during_persistence_rolls_back_complete_turn(
    chat_database: sessionmaker[Session],
) -> None:
    add_ready_document(chat_database)
    clock = FakeClock()
    engine = chat_database.kw["bind"]

    @event.listens_for(engine, "after_cursor_execute")
    def expire_after_message_insert(
        connection: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        if statement.lstrip().upper().startswith("INSERT INTO CHAT_MESSAGES"):
            clock.advance(6)

    try:
        with pytest.raises(ChatDeadlineExceededError):
            ask(
                chat_database,
                deadline_seconds=5,
                clock=clock,
            )
    finally:
        event.remove(engine, "after_cursor_execute", expire_after_message_insert)

    assert table_counts(chat_database) == (0, 0, 0)


def test_successful_commit_is_not_reported_as_timeout_if_commit_crosses_deadline(
    chat_database: sessionmaker[Session],
) -> None:
    add_ready_document(chat_database)
    clock = FakeClock()

    with chat_database() as db:
        @event.listens_for(db, "before_commit")
        def expire_during_commit(session: Session) -> None:
            clock.advance(6)

        result = ask_document(
            db,
            FakeRetrieval(chunks()),
            FakeAnswer(),
            document_id=1,
            user_id=7,
            question="Cau hoi",
            deadline_seconds=5,
            clock=clock,
        )

    assert result.assistant_message_id > 0
    assert table_counts(chat_database) == (1, 2, 1)


def test_retry_after_deadline_uses_a_fresh_budget_and_succeeds(
    chat_database: sessionmaker[Session],
) -> None:
    add_ready_document(chat_database)
    expired_clock = FakeClock()

    with pytest.raises(ChatDeadlineExceededError):
        ask(
            chat_database,
            answer=AdvancingAnswer(expired_clock, 6),
            deadline_seconds=5,
            clock=expired_clock,
        )

    result = ask(
        chat_database,
        deadline_seconds=5,
        clock=FakeClock(),
    )
    assert result.answer_text
    assert table_counts(chat_database) == (1, 2, 1)


@pytest.mark.parametrize("question", ["", "   ", None, "x" * 2001])
def test_invalid_questions_are_rejected(
    chat_database: sessionmaker[Session],
    question: object,
) -> None:
    with pytest.raises(InvalidChatRequestError):
        ask(chat_database, question=question)


def table_counts(factory: sessionmaker[Session]) -> tuple[int, int, int]:
    with factory() as db:
        return (
            db.scalar(select(func.count(ChatSession.id))) or 0,
            db.scalar(select(func.count(ChatMessage.id))) or 0,
            db.scalar(select(func.count(ChatCitation.id))) or 0,
        )
