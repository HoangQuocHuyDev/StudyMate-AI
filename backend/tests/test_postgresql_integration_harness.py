"""Unit tests for the fail-closed PostgreSQL integration harness."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from scripts.postgresql_integration import (
    APPLICATION_TABLES,
    DATABASE_URL_VARIABLE,
    EXPECTED_ALEMBIC_HEAD,
    OPT_IN_VARIABLE,
    PostgreSQLIntegrationConfigurationError,
    PostgreSQLIntegrationHarness,
    PostgreSQLIntegrationSafetyError,
    VerifiedPostgreSQLConnection,
    integration_is_requested,
    load_integration_target,
    reject_xdist,
)


VALID_URL = (
    "postgresql+psycopg://studymate_ai_test_runner:"
    "unit-test-password@127.0.0.1:5432/studymate_ai_test"
)


class FakeResult:
    def __init__(
        self,
        *,
        one: tuple[Any, ...] | None = None,
        rows: list[tuple[Any, ...]] | None = None,
        scalar: Any = None,
    ) -> None:
        self._one = one
        self._rows = rows or []
        self._scalar = scalar

    def one(self) -> tuple[Any, ...]:
        if self._one is None:
            raise AssertionError("No single row configured")
        return self._one

    def one_or_none(self) -> tuple[Any, ...] | None:
        return self._one

    def scalar_one(self) -> Any:
        return self._scalar

    def all(self) -> list[tuple[Any, ...]]:
        return self._rows


class FakeConnection:
    def __init__(
        self,
        *,
        database: str = "studymate_ai_test",
        username: str = "studymate_ai_test_runner",
        version_number: int = 180_000,
        role: tuple[bool, bool, bool, bool] = (False, False, False, False),
        lock_acquired: bool = True,
    ) -> None:
        self.database = database
        self.username = username
        self.version_number = version_number
        self.role = role
        self.lock_acquired = lock_acquired
        self.statements: list[str] = []

    def execute(
        self,
        statement: object,
        parameters: dict[str, int] | None = None,
    ) -> FakeResult:
        del parameters
        sql = str(statement)
        self.statements.append(sql)
        if "current_database()" in sql:
            return FakeResult(
                one=(self.database, self.username, self.version_number)
            )
        if "FROM pg_catalog.pg_roles" in sql:
            return FakeResult(one=self.role)
        if "pg_try_advisory_lock" in sql:
            return FakeResult(scalar=self.lock_acquired)
        if "pg_advisory_unlock" in sql:
            return FakeResult(scalar=True)
        if "SELECT version_num FROM alembic_version" in sql:
            return FakeResult(scalar=EXPECTED_ALEMBIC_HEAD)
        if "FROM pg_catalog.pg_tables" in sql:
            rows = [(name,) for name in (*APPLICATION_TABLES, "alembic_version")]
            return FakeResult(rows=rows)
        if sql.startswith("TRUNCATE TABLE"):
            return FakeResult()
        raise AssertionError(f"Unexpected statement type: {sql.split()[0]}")


def enabled_environment(url: str = VALID_URL) -> dict[str, str]:
    return {
        OPT_IN_VARIABLE: "1",
        DATABASE_URL_VARIABLE: url,
        # A production-shaped variable must be ignored completely.
        "DATABASE_URL": "postgresql+psycopg://ignored@127.0.0.1/studymate_ai_db",
    }


def harness() -> PostgreSQLIntegrationHarness:
    return PostgreSQLIntegrationHarness(
        load_integration_target(enabled_environment())
    )


def verify(
    target_harness: PostgreSQLIntegrationHarness,
    connection: FakeConnection,
) -> VerifiedPostgreSQLConnection:
    return target_harness.verify_connection(connection)  # type: ignore[arg-type]


def test_missing_opt_in_does_not_load_or_connect() -> None:
    assert integration_is_requested({}) is False


def test_invalid_opt_in_value_is_rejected() -> None:
    with pytest.raises(PostgreSQLIntegrationConfigurationError):
        integration_is_requested({OPT_IN_VARIABLE: "true"})


def test_opt_in_requires_dedicated_url_without_database_url_fallback() -> None:
    environment = {
        OPT_IN_VARIABLE: "1",
        "DATABASE_URL": VALID_URL,
    }
    with pytest.raises(PostgreSQLIntegrationConfigurationError):
        load_integration_target(environment)


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://studymate_ai_test_runner:x@127.0.0.1:5432/studymate_ai_test",
        "postgresql+psycopg://studymate_ai_test_runner:x@127.0.0.1:5432/studymate_ai_db",
        "postgresql+psycopg://studymate_ai_test_runner:x@127.0.0.1:5432/tiem_chung_db",
        "postgresql+psycopg://studymate_ai_test_runner:x@127.0.0.1:5432/other_test",
        "postgresql+psycopg://postgres:x@127.0.0.1:5432/studymate_ai_test",
        "postgresql+psycopg://studymate_ai_test_runner:x@localhost:5432/studymate_ai_test",
        "postgresql+psycopg://studymate_ai_test_runner:x@127.0.0.1:5433/studymate_ai_test",
    ],
)
def test_invalid_integration_url_targets_are_rejected_before_connect(
    url: str,
) -> None:
    with pytest.raises(PostgreSQLIntegrationConfigurationError):
        load_integration_target(enabled_environment(url))


def test_target_repr_and_configuration_errors_do_not_expose_password() -> None:
    password = "do-not-leak-this-password"
    valid = VALID_URL.replace("unit-test-password", password)
    target = load_integration_target(enabled_environment(valid))
    assert password not in repr(target)

    invalid = valid.replace("studymate_ai_test", "wrong_database", 1)
    with pytest.raises(PostgreSQLIntegrationConfigurationError) as captured:
        load_integration_target(enabled_environment(invalid))
    assert password not in str(captured.value)


@pytest.mark.parametrize(
    ("connection", "expected_fragment"),
    [
        (FakeConnection(database="studymate_ai_db"), "isolated test database"),
        (FakeConnection(database="tiem_chung_db"), "isolated test database"),
        (FakeConnection(username="postgres"), "isolated test role"),
        (FakeConnection(version_number=170_000), "major version"),
    ],
)
def test_preflight_rejects_wrong_server_identity(
    connection: FakeConnection,
    expected_fragment: str,
) -> None:
    with pytest.raises(PostgreSQLIntegrationSafetyError) as captured:
        verify(harness(), connection)
    assert expected_fragment in str(captured.value)


@pytest.mark.parametrize("dangerous_index", range(4))
def test_preflight_rejects_each_dangerous_role_privilege(
    dangerous_index: int,
) -> None:
    privileges = [False, False, False, False]
    privileges[dangerous_index] = True
    connection = FakeConnection(role=tuple(privileges))  # type: ignore[arg-type]
    with pytest.raises(PostgreSQLIntegrationSafetyError, match="elevated"):
        verify(harness(), connection)


def test_cleanup_requires_verification_from_the_same_connection() -> None:
    target_harness = harness()
    verified_connection = FakeConnection()
    verification = verify(target_harness, verified_connection)
    unverified_connection = FakeConnection()

    with pytest.raises(PostgreSQLIntegrationSafetyError, match="preflight"):
        target_harness.cleanup_database(
            unverified_connection,  # type: ignore[arg-type]
            verification,
        )
    assert not any(
        statement.startswith("TRUNCATE")
        for statement in unverified_connection.statements
    )


def test_cleanup_reverifies_target_and_uses_fixed_allowlist() -> None:
    target_harness = harness()
    connection = FakeConnection()
    verification = verify(target_harness, connection)
    target_harness.cleanup_database(  # type: ignore[arg-type]
        connection,
        verification,
    )

    cleanup_sql = next(
        statement
        for statement in connection.statements
        if statement.startswith("TRUNCATE TABLE")
    )
    assert "alembic_version" not in cleanup_sql
    assert "RESTART IDENTITY CASCADE" in cleanup_sql
    assert all(f'\"{name}\"' in cleanup_sql for name in APPLICATION_TABLES)


def test_cleanup_stops_if_identity_changes_after_preflight() -> None:
    target_harness = harness()
    connection = FakeConnection()
    verification = verify(target_harness, connection)
    connection.database = "studymate_ai_db"

    with pytest.raises(PostgreSQLIntegrationSafetyError, match="changed"):
        target_harness.cleanup_database(  # type: ignore[arg-type]
            connection,
            verification,
        )
    assert not any(
        statement.startswith("TRUNCATE") for statement in connection.statements
    )


def test_forged_verification_cannot_authorize_cleanup() -> None:
    target_harness = harness()
    connection = FakeConnection()
    forged = replace(
        VerifiedPostgreSQLConnection(
            connection_identity=0,
            database="studymate_ai_test",
            username="studymate_ai_test_runner",
            postgresql_major=18,
        ),
        connection_identity=0,
    )
    with pytest.raises(PostgreSQLIntegrationSafetyError):
        target_harness.cleanup_database(  # type: ignore[arg-type]
            connection,
            forged,
        )


def test_xdist_worker_is_rejected() -> None:
    with pytest.raises(PostgreSQLIntegrationConfigurationError, match="xdist"):
        reject_xdist({"PYTEST_XDIST_WORKER": "gw0"})


def test_second_test_suite_cannot_acquire_advisory_lock() -> None:
    target_harness = harness()
    connection = FakeConnection(lock_acquired=False)
    verification = verify(target_harness, connection)
    with pytest.raises(PostgreSQLIntegrationSafetyError, match="already running"):
        target_harness.acquire_suite_lock(  # type: ignore[arg-type]
            connection,
            verification,
        )


def test_schema_verification_accepts_only_expected_head_and_tables() -> None:
    target_harness = harness()
    connection = FakeConnection()
    verification = verify(target_harness, connection)
    target_harness.verify_migrated_schema(  # type: ignore[arg-type]
        connection,
        verification,
    )
