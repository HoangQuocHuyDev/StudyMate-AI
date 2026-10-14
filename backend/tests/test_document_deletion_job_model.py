"""Model and migration tests for durable document deletion jobs."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from importlib import import_module
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.schema import CreateIndex

from app import models
from app.db.base import Base
from app.models.document_deletion_job import DocumentDeletionJob


@pytest.fixture
def deletion_job_database() -> Iterator[sessionmaker[Session]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    DocumentDeletionJob.__table__.create(engine)
    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    yield factory
    engine.dispose()


def make_job(**overrides: object) -> DocumentDeletionJob:
    values: dict[str, object] = {
        "document_id": 1,
        "user_id": 7,
        "storage_key": "users/7/document.pdf",
    }
    values.update(overrides)
    return DocumentDeletionJob(**values)


def test_model_is_imported_and_registered_in_metadata() -> None:
    assert models.DocumentDeletionJob is DocumentDeletionJob
    assert "document_deletion_jobs" in Base.metadata.tables

    table = DocumentDeletionJob.__table__
    assert list(table.c.keys()) == [
        "id",
        "document_id",
        "user_id",
        "storage_key",
        "status",
        "current_step",
        "attempt_count",
        "lease_token",
        "lease_expires_at",
        "last_error_code",
        "last_error_at",
        "created_at",
        "updated_at",
        "completed_at",
    ]
    assert not table.foreign_keys
    assert table.c.storage_key.nullable is True
    assert table.c.lease_token.nullable is True
    assert table.c.lease_expires_at.type.timezone is True
    assert table.c.created_at.type.timezone is True
    assert table.c.updated_at.type.timezone is True
    assert table.c.completed_at.type.timezone is True
    assert str(table.c.status.server_default.arg) == "PENDING"
    assert str(table.c.current_step.server_default.arg) == "VECTOR_CLEANUP"
    assert str(table.c.attempt_count.server_default.arg) == "0"


def test_model_has_expected_constraints_and_postgresql_partial_indexes() -> None:
    table = DocumentDeletionJob.__table__
    constraint_names = {
        constraint.name for constraint in table.constraints if constraint.name
    }
    assert constraint_names == {
        "uq_document_deletion_jobs_document_id",
        "ck_document_deletion_jobs_document_id_positive",
        "ck_document_deletion_jobs_user_id_positive",
        "ck_document_deletion_jobs_attempt_count_nonnegative",
        "ck_document_deletion_jobs_status",
        "ck_document_deletion_jobs_current_step",
        "ck_document_deletion_jobs_storage_key_nonblank",
        "ck_document_deletion_jobs_last_error_code_nonblank",
        "ck_document_deletion_jobs_lease_consistency",
        "ck_document_deletion_jobs_completion_consistency",
        "ck_document_deletion_jobs_storage_key_step",
    }

    compiled_indexes = {
        index.name: str(CreateIndex(index).compile(dialect=postgresql.dialect()))
        for index in table.indexes
    }
    assert set(compiled_indexes) == {
        "uq_document_deletion_jobs_storage_key_not_null",
        "ix_document_deletion_jobs_retryable",
        "ix_document_deletion_jobs_expired_lease",
    }
    assert (
        "CREATE UNIQUE INDEX uq_document_deletion_jobs_storage_key_not_null"
        in compiled_indexes["uq_document_deletion_jobs_storage_key_not_null"]
    )
    assert "WHERE storage_key IS NOT NULL" in compiled_indexes[
        "uq_document_deletion_jobs_storage_key_not_null"
    ]
    assert "WHERE status IN ('PENDING', 'FAILED')" in compiled_indexes[
        "ix_document_deletion_jobs_retryable"
    ]
    assert "WHERE status = 'RUNNING'" in compiled_indexes[
        "ix_document_deletion_jobs_expired_lease"
    ]


def test_valid_job_can_progress_and_retry_without_becoming_stuck(
    deletion_job_database: sessionmaker[Session],
) -> None:
    now = datetime.now(timezone.utc)
    with deletion_job_database() as session:
        job = make_job()
        session.add(job)
        session.commit()
        assert (job.status, job.current_step, job.attempt_count) == (
            "PENDING",
            "VECTOR_CLEANUP",
            0,
        )

        job.status = "RUNNING"
        job.lease_token = uuid4()
        job.lease_expires_at = now + timedelta(minutes=1)
        job.attempt_count = 1
        session.commit()

        job.status = "FAILED"
        job.lease_token = None
        job.lease_expires_at = None
        job.last_error_code = "chroma_delete_failed"
        job.last_error_at = now
        session.commit()

        job.status = "RUNNING"
        job.current_step = "FILE_CLEANUP"
        job.lease_token = uuid4()
        job.lease_expires_at = now + timedelta(minutes=1)
        job.attempt_count = 2
        session.commit()

        job.current_step = "DATABASE_DELETE"
        job.storage_key = None
        session.commit()

        job.status = "FAILED"
        job.lease_token = None
        job.lease_expires_at = None
        job.last_error_code = "database_delete_failed"
        session.commit()

        job.status = "RUNNING"
        job.lease_token = uuid4()
        job.lease_expires_at = now + timedelta(minutes=1)
        job.attempt_count = 3
        session.commit()

        job.status = "COMPLETED"
        job.current_step = "DONE"
        job.lease_token = None
        job.lease_expires_at = None
        job.completed_at = now
        session.commit()

        assert job.status == "COMPLETED"
        assert job.current_step == "DONE"
        assert job.storage_key is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"document_id": 0},
        {"user_id": 0},
        {"attempt_count": -1},
        {"status": "UNKNOWN"},
        {"current_step": "UNKNOWN"},
        {"storage_key": "   "},
        {"last_error_code": "   "},
        {"status": "RUNNING"},
        {"status": "FAILED", "lease_token": uuid4()},
        {"status": "FAILED", "lease_expires_at": datetime.now(timezone.utc)},
        {"status": "COMPLETED", "current_step": "DONE"},
        {"current_step": "DONE"},
        {"storage_key": None, "current_step": "FILE_CLEANUP"},
    ],
)
def test_invalid_state_is_rejected(
    deletion_job_database: sessionmaker[Session],
    overrides: dict[str, object],
) -> None:
    with deletion_job_database() as session:
        session.add(make_job(**overrides))
        with pytest.raises(IntegrityError):
            session.commit()


def test_unique_document_and_non_null_storage_key_are_enforced(
    deletion_job_database: sessionmaker[Session],
) -> None:
    with deletion_job_database() as session:
        session.add(make_job())
        session.commit()
        session.add(make_job(document_id=2))
        with pytest.raises(IntegrityError):
            session.commit()

    with deletion_job_database() as session:
        session.add(make_job(document_id=1, storage_key="users/7/other.pdf"))
        with pytest.raises(IntegrityError):
            session.commit()


def test_migration_is_linear_additive_and_has_no_foreign_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = import_module(
        "migrations.versions.d9a4e7b2c610_create_document_deletion_jobs_table"
    )

    class OperationRecorder:
        def __init__(self) -> None:
            self.tables: list[tuple[str, tuple[object, ...]]] = []
            self.indexes: list[tuple[str, str, tuple[str, ...], bool, object]] = []

        def create_table(self, name: str, *items: object) -> None:
            self.tables.append((name, items))

        def create_index(
            self,
            name: str,
            table_name: str,
            columns: list[str],
            *,
            unique: bool,
            postgresql_where: object,
        ) -> None:
            self.indexes.append(
                (name, table_name, tuple(columns), unique, postgresql_where)
            )

    recorder = OperationRecorder()
    monkeypatch.setattr(migration, "op", recorder)
    migration.upgrade()

    assert migration.revision == "d9a4e7b2c610"
    assert migration.down_revision == "c8f1a6d3e905"
    assert migration.branch_labels is None
    assert migration.depends_on is None
    assert len(recorder.tables) == 1
    assert recorder.tables[0][0] == "document_deletion_jobs"
    assert not any(
        item.__class__.__name__ == "ForeignKeyConstraint"
        for item in recorder.tables[0][1]
    )
    assert {index[0] for index in recorder.indexes} == {
        "uq_document_deletion_jobs_storage_key_not_null",
        "ix_document_deletion_jobs_retryable",
        "ix_document_deletion_jobs_expired_lease",
    }


def test_downgrade_contains_unfinished_job_guard() -> None:
    migration = import_module(
        "migrations.versions.d9a4e7b2c610_create_document_deletion_jobs_table"
    )

    class OperationRecorder:
        def __init__(self) -> None:
            self.sql: list[str] = []
            self.dropped_indexes: list[str] = []
            self.dropped_tables: list[str] = []

        def execute(self, statement: str) -> None:
            self.sql.append(statement)

        def drop_index(self, name: str, *, table_name: str) -> None:
            assert table_name == "document_deletion_jobs"
            self.dropped_indexes.append(name)

        def drop_table(self, name: str) -> None:
            self.dropped_tables.append(name)

    recorder = OperationRecorder()
    original_op = migration.op
    migration.op = recorder
    try:
        migration.downgrade()
    finally:
        migration.op = original_op

    assert len(recorder.sql) == 1
    assert "WHERE status <> 'COMPLETED'" in recorder.sql[0]
    assert "RAISE EXCEPTION" in recorder.sql[0]
    assert recorder.dropped_tables == ["document_deletion_jobs"]


def test_sqlite_schema_has_no_foreign_keys(
    deletion_job_database: sessionmaker[Session],
) -> None:
    with deletion_job_database() as session:
        inspector = inspect(session.get_bind())
        assert inspector.get_foreign_keys("document_deletion_jobs") == []
