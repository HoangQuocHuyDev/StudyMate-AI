"""Tests for owner-scoped hierarchical document summaries."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from threading import Event, Thread

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
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.services.summary.document_summary as summary_module
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.document_deletion_job import DocumentDeletionJob
from app.models.document_summary import DocumentSummary
from app.models.user import User
from app.services.summary.document_summary import (
    DocumentSummaryConflictError,
    DocumentSummaryDeadlineExceededError,
    DocumentSummaryGenerationError,
    DocumentSummaryLimitError,
    DocumentSummaryPersistenceError,
    DocumentSummaryResult,
    InvalidDocumentSummaryRequestError,
    SummaryDocumentHasNoChunksError,
    SummaryDocumentNotFoundError,
    SummaryDocumentNotReadyError,
    SummaryLimits,
    summarize_document,
)
from app.services.summary.concurrency import (
    InProcessSummaryConcurrencyCoordinator,
    SummaryConcurrencyCoordinator,
    SummaryConcurrencyLimitError,
    SummaryConcurrencyLimits,
    SummaryGenerationBusyError,
)
from app.services.summary.gemini_summary import GeneratedSummary
from app.services.summary.gemini_summary import GeminiSummaryTimeoutError


@pytest.fixture
def summary_service_database() -> Iterator[sessionmaker[Session]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
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
    yield factory
    engine.dispose()


class FakeSummaryProvider:
    def __init__(
        self,
        *,
        response_factory: Callable[[str, str, str, int], str] | None = None,
        error: Exception | None = None,
        session: Session | None = None,
        on_call: Callable[[], None] | None = None,
    ) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.response_factory = response_factory
        self.error = error
        self.session = session
        self.on_call = on_call

    def generate_summary(
        self,
        content: str,
        summary_type: str,
        *,
        stage: str,
        timeout_seconds: float | None = None,
    ) -> GeneratedSummary:
        if self.session is not None:
            assert not self.session.in_transaction()
        self.calls.append((content, summary_type, stage))
        assert timeout_seconds is not None and timeout_seconds > 0
        if self.on_call is not None:
            callback, self.on_call = self.on_call, None
            callback()
        if self.error is not None:
            raise self.error
        generated = (
            self.response_factory(content, summary_type, stage, len(self.calls))
            if self.response_factory
            else f"Tóm tắt {summary_type} {stage}"
        )
        return GeneratedSummary(generated, "fake-gemini")


class ManualClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class ExpiringStageProvider(FakeSummaryProvider):
    def __init__(
        self,
        clock: ManualClock,
        target_stage: str,
        *,
        raise_timeout: bool = False,
    ) -> None:
        super().__init__()
        self.clock = clock
        self.target_stage = target_stage
        self.raise_timeout = raise_timeout
        self.timeouts: list[float] = []

    def generate_summary(
        self,
        content: str,
        summary_type: str,
        *,
        stage: str,
        timeout_seconds: float | None = None,
    ) -> GeneratedSummary:
        assert timeout_seconds is not None
        self.timeouts.append(timeout_seconds)
        self.calls.append((content, summary_type, stage))
        if stage == self.target_stage:
            self.clock.advance(2)
            if self.raise_timeout:
                raise GeminiSummaryTimeoutError("safe timeout")
        generated = "M" * 60 if stage == "MAP" else "R" * 10
        return GeneratedSummary(generated, "fake-gemini")


def add_document(
    factory: sessionmaker[Session],
    *,
    document_id: int = 1,
    user_id: int = 7,
    status: str = "READY",
    chunks: list[tuple[int, str]] | None = None,
) -> None:
    now = datetime.now(timezone.utc)
    with factory() as db:
        if db.get(User, user_id) is None:
            db.add(User(
                id=user_id,
                full_name=f"User {user_id}",
                username=f"user_{user_id}",
                password_hash="test-hash",
                role="USER",
                is_active=True,
                created_at=now,
            ))
            db.flush()
        db.add(Document(
            id=document_id,
            user_id=user_id,
            title="Tài liệu kiểm thử",
            original_filename="test.docx",
            storage_key=f"users/{user_id}/summary-{document_id}",
            file_type="DOCX",
            mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            file_size=100,
            status=status,
            rag_status="PENDING",
            created_at=now,
            updated_at=now,
        ))
        db.flush()
        for position, (chunk_index, content) in enumerate(chunks or []):
            db.add(DocumentChunk(
                id=document_id * 100 + position + 1,
                document_id=document_id,
                chunk_index=chunk_index,
                content=content,
                start_char=position * 100,
                end_char=position * 100 + len(content),
                character_count=len(content),
                page_number=None,
                created_at=now,
            ))
        db.commit()


def default_chunks() -> list[tuple[int, str]]:
    return [(0, "Phần đầu tài liệu."), (1, "Phần cuối tài liệu.")]


def call(
    factory: sessionmaker[Session],
    provider: FakeSummaryProvider,
    *,
    summary_type: str = "STANDARD",
    document_id: int = 1,
    user_id: int = 7,
    limits: SummaryLimits | None = None,
    concurrency_limits: SummaryConcurrencyLimits | None = None,
    concurrency_coordinator: SummaryConcurrencyCoordinator | None = None,
    deadline_seconds: float = 120.0,
    clock: Callable[[], float] | None = None,
) -> DocumentSummaryResult:
    with factory() as db:
        arguments = {
            "document_id": document_id,
            "user_id": user_id,
            "summary_type": summary_type,
            "limits": limits,
            "concurrency_limits": concurrency_limits,
            "concurrency_coordinator": concurrency_coordinator,
            "deadline_seconds": deadline_seconds,
        }
        if clock is not None:
            arguments["clock"] = clock
        return summarize_document(
            db,
            provider,
            **arguments,
        )


@pytest.mark.parametrize("summary_type", ["SHORT", "STANDARD", "DETAILED"])
def test_all_supported_summary_types_are_generated_and_saved(
    summary_service_database: sessionmaker[Session],
    summary_type: str,
) -> None:
    add_document(summary_service_database, chunks=default_chunks())
    result = call(summary_service_database, FakeSummaryProvider(), summary_type=summary_type)
    assert result.summary_type == summary_type
    assert result.from_cache is False
    assert result.summary_id > 0
    with summary_service_database() as db:
        saved = db.scalar(select(DocumentSummary))
        assert saved is not None
        assert saved.content == result.content
        document = db.get(Document, 1)
        assert document.status == "READY"
        assert document.rag_status == "PENDING"


def test_other_user_and_missing_document_are_indistinguishable(
    summary_service_database: sessionmaker[Session],
) -> None:
    add_document(summary_service_database, chunks=default_chunks())
    provider = FakeSummaryProvider()
    with pytest.raises(SummaryDocumentNotFoundError):
        call(summary_service_database, provider, user_id=8)
    with pytest.raises(SummaryDocumentNotFoundError):
        call(summary_service_database, provider, document_id=999)
    assert provider.calls == []


def test_document_must_be_ready_and_have_chunks(
    summary_service_database: sessionmaker[Session],
) -> None:
    add_document(summary_service_database, status="UPLOADED", chunks=[])
    with pytest.raises(SummaryDocumentNotReadyError):
        call(summary_service_database, FakeSummaryProvider())

    with summary_service_database() as db:
        db.get(Document, 1).status = "READY"
        db.commit()
    with pytest.raises(SummaryDocumentHasNoChunksError):
        call(summary_service_database, FakeSummaryProvider())


@pytest.mark.parametrize("summary_type", ["", "CUSTOM", None])
def test_invalid_summary_type_is_rejected_before_database(
    summary_service_database: sessionmaker[Session],
    summary_type: object,
) -> None:
    with pytest.raises(InvalidDocumentSummaryRequestError):
        call(summary_service_database, FakeSummaryProvider(), summary_type=summary_type)  # type: ignore[arg-type]


def test_chunks_are_ordered_and_short_document_uses_one_request(
    summary_service_database: sessionmaker[Session],
) -> None:
    add_document(
        summary_service_database,
        chunks=[(2, "THIRD"), (0, "FIRST"), (1, "SECOND")],
    )
    provider = FakeSummaryProvider()
    call(summary_service_database, provider)
    assert len(provider.calls) == 1
    content, _, stage = provider.calls[0]
    assert stage == "FINAL"
    assert content.index("FIRST") < content.index("SECOND") < content.index("THIRD")


def test_long_document_uses_hierarchy_keeps_last_chunk_and_bounds_context(
    summary_service_database: sessionmaker[Session],
) -> None:
    add_document(
        summary_service_database,
        chunks=[(0, "A" * 70), (1, "B" * 70), (2, "FINAL_CHUNK_MARKER")],
    )
    limits = SummaryLimits(
        max_group_chars=80,
        max_document_chars=500,
        max_provider_input_chars=2_000,
        max_requests=20,
        max_reduction_rounds=3,
    )
    provider = FakeSummaryProvider(
        response_factory=lambda content, kind, stage, count: f"s{count}-{stage}"
    )
    call(summary_service_database, provider, limits=limits)
    assert len(provider.calls) > 2
    assert all(len(content) <= limits.max_group_chars for content, _, _ in provider.calls)
    map_inputs = "\n".join(content for content, _, stage in provider.calls if stage == "MAP")
    assert "FINAL_CHUNK_MARKER" in map_inputs
    assert provider.calls[-1][2] == "FINAL"


def test_oversized_single_chunk_is_split_without_dropping_tail(
    summary_service_database: sessionmaker[Session],
) -> None:
    tail = "UNIQUE_END_MARKER"
    add_document(summary_service_database, chunks=[(0, "X" * 190 + tail)])
    provider = FakeSummaryProvider(
        response_factory=lambda content, kind, stage, count: f"r{count}"
    )
    limits = SummaryLimits(80, 500, 2_000, 20, 3)
    call(summary_service_database, provider, limits=limits)
    map_input = "\n".join(item[0] for item in provider.calls if item[2] == "MAP")
    assert "UNIQUE_END" in map_input
    assert "_MARKER" in map_input


def test_non_reducing_intermediate_summaries_are_rejected(
    summary_service_database: sessionmaker[Session],
) -> None:
    add_document(summary_service_database, chunks=[(0, "A" * 100), (1, "B" * 100)])
    provider = FakeSummaryProvider(response_factory=lambda *args: "Y" * 100)
    limits = SummaryLimits(80, 500, 5_000, 20, 2)
    with pytest.raises(DocumentSummaryLimitError):
        call(summary_service_database, provider, limits=limits)


def test_request_and_document_budgets_are_enforced(
    summary_service_database: sessionmaker[Session],
) -> None:
    add_document(summary_service_database, chunks=[(0, "A" * 90), (1, "B" * 90)])
    with pytest.raises(DocumentSummaryLimitError):
        call(
            summary_service_database,
            FakeSummaryProvider(),
            limits=SummaryLimits(80, 100, 500, 10, 2),
        )
    with pytest.raises(DocumentSummaryLimitError):
        call(
            summary_service_database,
            FakeSummaryProvider(response_factory=lambda *args: "short"),
            limits=SummaryLimits(80, 500, 500, 1, 2),
        )


def test_cache_hit_skips_provider(
    summary_service_database: sessionmaker[Session],
) -> None:
    add_document(summary_service_database, chunks=default_chunks())
    first = call(summary_service_database, FakeSummaryProvider())
    provider = FakeSummaryProvider(error=AssertionError("must not call"))
    second = call(summary_service_database, provider)
    assert second.summary_id == first.summary_id
    assert second.from_cache is True
    assert provider.calls == []


def test_cache_does_not_bypass_current_ready_and_chunk_checks(
    summary_service_database: sessionmaker[Session],
) -> None:
    add_document(summary_service_database, chunks=default_chunks())
    call(summary_service_database, FakeSummaryProvider())
    with summary_service_database() as db:
        db.get(Document, 1).status = "FAILED"
        db.commit()
    provider = FakeSummaryProvider(error=AssertionError("must not call"))
    with pytest.raises(SummaryDocumentNotReadyError):
        call(summary_service_database, provider)
    assert provider.calls == []


def test_provider_failure_leaves_no_summary_and_hides_sensitive_data(
    summary_service_database: sessionmaker[Session],
) -> None:
    add_document(summary_service_database, chunks=default_chunks())
    provider = FakeSummaryProvider(error=RuntimeError("api-key SECRET_CONTENT"))
    with pytest.raises(DocumentSummaryGenerationError) as captured:
        call(summary_service_database, provider)
    assert "secret" not in str(captured.value).lower()
    with summary_service_database() as db:
        assert db.scalar(select(func.count(DocumentSummary.id))) == 0


def test_no_transaction_is_open_during_provider_call(
    summary_service_database: sessionmaker[Session],
) -> None:
    add_document(summary_service_database, chunks=default_chunks())
    with summary_service_database() as db:
        provider = FakeSummaryProvider(session=db)
        summarize_document(
            db,
            provider,
            document_id=1,
            user_id=7,
            summary_type="SHORT",
        )


def test_database_failure_rolls_back_summary(
    summary_service_database: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    add_document(summary_service_database, chunks=default_chunks())
    with summary_service_database() as db:
        monkeypatch.setattr(
            db,
            "commit",
            lambda: (_ for _ in ()).throw(SQLAlchemyError("sensitive SQL")),
        )
        with pytest.raises(DocumentSummaryPersistenceError) as captured:
            summarize_document(
                db,
                FakeSummaryProvider(),
                document_id=1,
                user_id=7,
                summary_type="SHORT",
            )
        assert "sensitive" not in str(captured.value).lower()
    with summary_service_database() as db:
        assert db.scalar(select(func.count(DocumentSummary.id))) == 0


def test_deleted_document_during_generation_is_not_saved(
    summary_service_database: sessionmaker[Session],
) -> None:
    add_document(summary_service_database, chunks=default_chunks())

    def delete_document() -> None:
        with summary_service_database() as other:
            other.delete(other.get(Document, 1))
            other.commit()

    provider = FakeSummaryProvider(on_call=delete_document)
    with pytest.raises(SummaryDocumentNotFoundError):
        call(summary_service_database, provider)


def test_tombstone_created_during_generation_prevents_summary_write(
    summary_service_database: sessionmaker[Session],
) -> None:
    add_document(summary_service_database, chunks=default_chunks())

    def create_tombstone() -> None:
        with summary_service_database() as other:
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

    provider = FakeSummaryProvider(on_call=create_tombstone)
    with pytest.raises(SummaryDocumentNotFoundError):
        call(summary_service_database, provider)
    with summary_service_database() as db:
        assert db.scalar(select(func.count(DocumentSummary.id))) == 0


def test_changed_document_status_during_generation_is_not_saved(
    summary_service_database: sessionmaker[Session],
) -> None:
    add_document(summary_service_database, chunks=default_chunks())

    def change_status() -> None:
        with summary_service_database() as other:
            other.get(Document, 1).status = "FAILED"
            other.commit()

    provider = FakeSummaryProvider(on_call=change_status)
    with pytest.raises(SummaryDocumentNotReadyError):
        call(summary_service_database, provider)


def test_changed_chunks_during_generation_raise_conflict(
    summary_service_database: sessionmaker[Session],
) -> None:
    add_document(summary_service_database, chunks=default_chunks())

    def change_chunk() -> None:
        with summary_service_database() as other:
            chunk = other.scalar(select(DocumentChunk).where(DocumentChunk.chunk_index == 1))
            chunk.content = "Nội dung đã thay đổi"
            chunk.end_char = chunk.start_char + len(chunk.content)
            chunk.character_count = len(chunk.content)
            other.commit()

    with pytest.raises(DocumentSummaryConflictError):
        call(summary_service_database, FakeSummaryProvider(on_call=change_chunk))


def test_integrity_race_can_return_concurrent_cached_result(
    summary_service_database: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    add_document(summary_service_database, chunks=default_chunks())
    concurrent = DocumentSummaryResult(
        summary_id=99,
        document_id=1,
        summary_type="SHORT",
        content="Concurrent summary",
        model_name="fake-gemini",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        from_cache=True,
    )
    with summary_service_database() as db:
        original_flush = db.flush
        calls = 0

        def conflicting_flush(*args: object, **kwargs: object) -> None:
            nonlocal calls
            calls += 1
            if any(isinstance(item, DocumentSummary) for item in db.new):
                from sqlalchemy.exc import IntegrityError
                raise IntegrityError("statement", {}, Exception("duplicate secret"))
            original_flush(*args, **kwargs)

        monkeypatch.setattr(db, "flush", conflicting_flush)
        monkeypatch.setattr(
            summary_module,
            "_load_cached_after_conflict",
            lambda *args, **kwargs: concurrent,
        )
        result = summarize_document(
            db,
            FakeSummaryProvider(),
            document_id=1,
            user_id=7,
            summary_type="SHORT",
        )
    assert calls >= 1
    assert result == concurrent


def test_simultaneous_cache_miss_calls_only_one_provider(
    summary_service_database: sessionmaker[Session],
) -> None:
    add_document(summary_service_database, chunks=default_chunks())
    engine = summary_service_database.kw["bind"]
    coordinator = InProcessSummaryConcurrencyCoordinator(
        engine,
        SummaryConcurrencyLimits(global_limit=2, per_user_limit=1),
    )
    provider_entered = Event()
    release_provider = Event()
    first_result: list[DocumentSummaryResult] = []
    first_errors: list[BaseException] = []

    def block_provider() -> None:
        provider_entered.set()
        assert release_provider.wait(timeout=5)

    first_provider = FakeSummaryProvider(on_call=block_provider)

    def run_first() -> None:
        try:
            first_result.append(call(
                summary_service_database,
                first_provider,
                concurrency_coordinator=coordinator,
            ))
        except BaseException as error:  # pragma: no cover - assertion aid
            first_errors.append(error)

    worker = Thread(target=run_first)
    worker.start()
    assert provider_entered.wait(timeout=5)
    duplicate_provider = FakeSummaryProvider()
    try:
        with pytest.raises(SummaryGenerationBusyError):
            call(
                summary_service_database,
                duplicate_provider,
                concurrency_coordinator=coordinator,
            )
    finally:
        release_provider.set()
        worker.join(timeout=5)

    assert not worker.is_alive()
    assert first_errors == []
    assert len(first_result) == 1
    assert len(first_provider.calls) == 1
    assert duplicate_provider.calls == []

    retry_provider = FakeSummaryProvider(error=AssertionError("must not call"))
    cached = call(
        summary_service_database,
        retry_provider,
        concurrency_coordinator=coordinator,
    )
    assert cached.from_cache is True
    assert cached.summary_id == first_result[0].summary_id
    assert retry_provider.calls == []


def test_per_user_concurrency_limit_blocks_a_different_document(
    summary_service_database: sessionmaker[Session],
) -> None:
    add_document(summary_service_database, document_id=1, chunks=default_chunks())
    add_document(summary_service_database, document_id=2, chunks=default_chunks())
    coordinator = InProcessSummaryConcurrencyCoordinator(
        summary_service_database.kw["bind"],
        SummaryConcurrencyLimits(global_limit=2, per_user_limit=1),
    )
    provider_entered = Event()
    release_provider = Event()
    errors: list[BaseException] = []

    def run_first() -> None:
        try:
            call(
                summary_service_database,
                FakeSummaryProvider(
                    on_call=lambda: (
                        provider_entered.set(),
                        release_provider.wait(timeout=5),
                    )
                ),
                document_id=1,
                concurrency_coordinator=coordinator,
            )
        except BaseException as error:  # pragma: no cover - assertion aid
            errors.append(error)

    worker = Thread(target=run_first)
    worker.start()
    assert provider_entered.wait(timeout=5)
    try:
        with pytest.raises(SummaryConcurrencyLimitError):
            call(
                summary_service_database,
                FakeSummaryProvider(),
                document_id=2,
                concurrency_coordinator=coordinator,
            )
    finally:
        release_provider.set()
        worker.join(timeout=5)
    assert errors == []


def test_global_concurrency_limit_applies_across_users(
    summary_service_database: sessionmaker[Session],
) -> None:
    add_document(
        summary_service_database,
        document_id=1,
        user_id=7,
        chunks=default_chunks(),
    )
    add_document(
        summary_service_database,
        document_id=2,
        user_id=8,
        chunks=default_chunks(),
    )
    coordinator = InProcessSummaryConcurrencyCoordinator(
        summary_service_database.kw["bind"],
        SummaryConcurrencyLimits(global_limit=1, per_user_limit=1),
    )
    provider_entered = Event()
    release_provider = Event()
    errors: list[BaseException] = []

    def block_provider() -> None:
        provider_entered.set()
        assert release_provider.wait(timeout=5)

    def run_first() -> None:
        try:
            call(
                summary_service_database,
                FakeSummaryProvider(on_call=block_provider),
                document_id=1,
                user_id=7,
                concurrency_coordinator=coordinator,
            )
        except BaseException as error:  # pragma: no cover - assertion aid
            errors.append(error)

    worker = Thread(target=run_first)
    worker.start()
    assert provider_entered.wait(timeout=5)
    try:
        with pytest.raises(SummaryConcurrencyLimitError):
            call(
                summary_service_database,
                FakeSummaryProvider(),
                document_id=2,
                user_id=8,
                concurrency_coordinator=coordinator,
            )
    finally:
        release_provider.set()
        worker.join(timeout=5)
    assert errors == []


def test_provider_failure_releases_generation_and_capacity_locks(
    summary_service_database: sessionmaker[Session],
) -> None:
    add_document(summary_service_database, chunks=default_chunks())
    coordinator = InProcessSummaryConcurrencyCoordinator(
        summary_service_database.kw["bind"],
        SummaryConcurrencyLimits(global_limit=1, per_user_limit=1),
    )
    with pytest.raises(DocumentSummaryGenerationError):
        call(
            summary_service_database,
            FakeSummaryProvider(error=RuntimeError("provider failed")),
            concurrency_coordinator=coordinator,
        )

    retry = call(
        summary_service_database,
        FakeSummaryProvider(),
        concurrency_coordinator=coordinator,
    )
    assert retry.from_cache is False


def test_cache_is_rechecked_after_generation_lock_is_acquired(
    summary_service_database: sessionmaker[Session],
) -> None:
    add_document(summary_service_database, chunks=default_chunks())

    class NeverCapacityLease:
        @contextmanager
        def capacity(self, user_id: int) -> Iterator[None]:
            del user_id
            raise AssertionError("cache hit must not claim capacity")
            yield

    class CommitCacheBeforeLease:
        @contextmanager
        def deduplicate(
            self,
            document_id: int,
            summary_type: str,
        ) -> Iterator[NeverCapacityLease]:
            with summary_service_database() as other:
                other.add(DocumentSummary(
                    document_id=document_id,
                    summary_type=summary_type,
                    content="Concurrent cached summary",
                    model_name="fake-gemini",
                ))
                other.commit()
            yield NeverCapacityLease()

    provider = FakeSummaryProvider(error=AssertionError("must not call"))
    result = call(
        summary_service_database,
        provider,
        concurrency_coordinator=CommitCacheBeforeLease(),
    )
    assert result.from_cache is True
    assert result.content == "Concurrent cached summary"
    assert provider.calls == []


def test_deadline_expires_during_map_without_saving_partial_summary(
    summary_service_database: sessionmaker[Session],
) -> None:
    add_document(
        summary_service_database,
        chunks=[(0, "A" * 100), (1, "B" * 100)],
    )
    clock = ManualClock()
    provider = ExpiringStageProvider(clock, "MAP")
    with pytest.raises(DocumentSummaryDeadlineExceededError):
        call(
            summary_service_database,
            provider,
            limits=SummaryLimits(80, 500, 5_000, 20, 3),
            deadline_seconds=1,
            clock=clock,
        )
    assert provider.calls[0][2] == "MAP"
    with summary_service_database() as db:
        assert db.scalar(select(func.count(DocumentSummary.id))) == 0


def test_deadline_expires_during_reduce_without_saving_partial_summary(
    summary_service_database: sessionmaker[Session],
) -> None:
    add_document(
        summary_service_database,
        chunks=[(0, "A" * 100), (1, "B" * 100)],
    )
    clock = ManualClock()
    provider = ExpiringStageProvider(clock, "REDUCE")
    with pytest.raises(DocumentSummaryDeadlineExceededError):
        call(
            summary_service_database,
            provider,
            limits=SummaryLimits(80, 500, 5_000, 20, 3),
            deadline_seconds=1,
            clock=clock,
        )
    assert "REDUCE" in [stage for _, _, stage in provider.calls]
    with summary_service_database() as db:
        assert db.scalar(select(func.count(DocumentSummary.id))) == 0


def test_deadline_expires_during_final_and_releases_all_locks_for_retry(
    summary_service_database: sessionmaker[Session],
) -> None:
    add_document(summary_service_database, chunks=default_chunks())
    coordinator = InProcessSummaryConcurrencyCoordinator(
        summary_service_database.kw["bind"],
        SummaryConcurrencyLimits(global_limit=1, per_user_limit=1),
    )
    clock = ManualClock()
    provider = ExpiringStageProvider(clock, "FINAL")
    with pytest.raises(DocumentSummaryDeadlineExceededError):
        call(
            summary_service_database,
            provider,
            concurrency_coordinator=coordinator,
            deadline_seconds=1,
            clock=clock,
        )
    assert provider.calls[-1][2] == "FINAL"
    with summary_service_database() as db:
        assert db.scalar(select(func.count(DocumentSummary.id))) == 0

    retry = call(
        summary_service_database,
        FakeSummaryProvider(),
        concurrency_coordinator=coordinator,
    )
    assert retry.from_cache is False


def test_provider_timeout_before_overall_deadline_is_retryable(
    summary_service_database: sessionmaker[Session],
) -> None:
    add_document(summary_service_database, chunks=default_chunks())
    coordinator = InProcessSummaryConcurrencyCoordinator(
        summary_service_database.kw["bind"],
        SummaryConcurrencyLimits(global_limit=1, per_user_limit=1),
    )
    clock = ManualClock()
    with pytest.raises(GeminiSummaryTimeoutError):
        call(
            summary_service_database,
            FakeSummaryProvider(error=GeminiSummaryTimeoutError("timeout")),
            concurrency_coordinator=coordinator,
            deadline_seconds=10,
            clock=clock,
        )
    retry = call(
        summary_service_database,
        FakeSummaryProvider(),
        concurrency_coordinator=coordinator,
    )
    assert retry.from_cache is False


def test_provider_timeout_at_remaining_deadline_becomes_deadline_error(
    summary_service_database: sessionmaker[Session],
) -> None:
    add_document(summary_service_database, chunks=default_chunks())
    clock = ManualClock()
    provider = ExpiringStageProvider(clock, "FINAL", raise_timeout=True)
    with pytest.raises(DocumentSummaryDeadlineExceededError):
        call(
            summary_service_database,
            provider,
            deadline_seconds=1,
            clock=clock,
        )
    with summary_service_database() as db:
        assert db.scalar(select(func.count(DocumentSummary.id))) == 0
