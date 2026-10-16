"""Fail-closed fixtures for the isolated PostgreSQL integration suite."""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from scripts.postgresql_integration import (
    PostgreSQLIntegrationConfigurationError,
    PostgreSQLIntegrationHarness,
    VerifiedPostgreSQLConnection,
    integration_is_requested,
    load_integration_target,
    reject_xdist,
    safe_error_message,
)


@dataclass
class FakeIntegrationVectorStore:
    """In-memory vectors for integration tests; never opens ChromaDB."""

    vectors: dict[tuple[int, int], set[str]] = field(default_factory=dict)

    def delete_document_vectors(self, *, user_id: int, document_id: int) -> None:
        self.vectors.pop((user_id, document_id), None)

    def get_document_vector_ids(
        self,
        *,
        user_id: int,
        document_id: int,
    ) -> set[str]:
        return set(self.vectors.get((user_id, document_id), set()))


@dataclass(frozen=True, slots=True)
class PostgreSQLIntegrationRuntime:
    harness: PostgreSQLIntegrationHarness
    engine: Engine
    lock_connection: object
    lock_verification: VerifiedPostgreSQLConnection


@pytest.fixture(scope="session", autouse=True)
def postgresql_integration_runtime() -> Iterator[PostgreSQLIntegrationRuntime]:
    """Opt in, validate, lock, and verify the pre-migrated test database."""

    try:
        requested = integration_is_requested(os.environ)
    except PostgreSQLIntegrationConfigurationError as error:
        pytest.fail(safe_error_message(error), pytrace=False)
    if not requested:
        pytest.skip(
            "PostgreSQL integration tests require explicit opt-in.",
            allow_module_level=True,
        )

    try:
        reject_xdist(os.environ)
        target = load_integration_target(os.environ)
    except PostgreSQLIntegrationConfigurationError as error:
        pytest.fail(safe_error_message(error), pytrace=False)

    engine = None
    lock_connection = None
    try:
        engine = create_engine(target.url, poolclass=NullPool)
        harness = PostgreSQLIntegrationHarness(target)
        lock_connection = engine.connect().execution_options(
            isolation_level="AUTOCOMMIT"
        )
        lock_verification = harness.verify_connection(lock_connection)
        harness.acquire_suite_lock(lock_connection, lock_verification)
        with engine.connect() as schema_connection:
            schema_verification = harness.verify_connection(schema_connection)
            harness.verify_migrated_schema(
                schema_connection,
                schema_verification,
            )
            schema_connection.rollback()
        yield PostgreSQLIntegrationRuntime(
            harness=harness,
            engine=engine,
            lock_connection=lock_connection,
            lock_verification=lock_verification,
        )
    except Exception as error:
        pytest.fail(safe_error_message(error), pytrace=False)
    finally:
        if lock_connection is not None:
            lock_connection.close()
        if engine is not None:
            engine.dispose()


@pytest.fixture(autouse=True)
def clean_postgresql_integration_database(
    postgresql_integration_runtime: PostgreSQLIntegrationRuntime,
) -> Iterator[None]:
    """Clean the allowlisted tables before and after every integration test."""

    runtime = postgresql_integration_runtime
    _clean_database(runtime)
    yield
    _clean_database(runtime)


def _clean_database(runtime: PostgreSQLIntegrationRuntime) -> None:
    try:
        with runtime.engine.begin() as connection:
            verification = runtime.harness.verify_connection(connection)
            runtime.harness.cleanup_database(connection, verification)
    except Exception as error:
        pytest.fail(safe_error_message(error), pytrace=False)


@pytest.fixture
def postgresql_session_factory(
    postgresql_integration_runtime: PostgreSQLIntegrationRuntime,
) -> sessionmaker[Session]:
    """Return a factory; each concurrency worker must open its own Session."""

    return sessionmaker(
        bind=postgresql_integration_runtime.engine,
        expire_on_commit=False,
    )


@pytest.fixture
def integration_vector_store() -> FakeIntegrationVectorStore:
    return FakeIntegrationVectorStore()


@pytest.fixture
def integration_storage_root(tmp_path: Path) -> Path:
    """Keep all file operations inside pytest's temporary directory."""

    storage_root = tmp_path / "documents"
    storage_root.mkdir()
    return storage_root
