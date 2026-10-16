"""Fail-closed support for the disposable PostgreSQL integration database.

This module never reads the application's ``DATABASE_URL``.  Callers must opt
in explicitly and supply the dedicated integration URL.  No connection is
opened at import time.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.engine import Connection, URL, make_url
from sqlalchemy.exc import ArgumentError, SQLAlchemyError


OPT_IN_VARIABLE = "STUDYMATE_RUN_POSTGRES_INTEGRATION"
DATABASE_URL_VARIABLE = "STUDYMATE_INTEGRATION_DATABASE_URL"
EXPECTED_DRIVER = "postgresql+psycopg"
EXPECTED_DATABASE = "studymate_ai_test"
EXPECTED_USERNAME = "studymate_ai_test_runner"
EXPECTED_HOST = "127.0.0.1"
EXPECTED_PORT = 5432
EXPECTED_POSTGRESQL_MAJOR = 18
EXPECTED_ALEMBIC_HEAD = "d9a4e7b2c610"
FORBIDDEN_DATABASES = frozenset({"studymate_ai_db", "tiem_chung_db"})
SUITE_ADVISORY_LOCK_KEY = 7_231_945_821_611_107_091

APPLICATION_TABLES = (
    "chat_citations",
    "chat_messages",
    "chat_sessions",
    "document_summaries",
    "document_chunks",
    "document_deletion_jobs",
    "documents",
    "users",
)
_CLEANUP_SQL = text(
    "TRUNCATE TABLE "
    + ", ".join(f'\"{table_name}\"' for table_name in APPLICATION_TABLES)
    + " RESTART IDENTITY CASCADE"
)
_IDENTITY_SQL = text(
    "SELECT current_database(), current_user, "
    "current_setting('server_version_num')::integer"
)
_ROLE_SQL = text(
    "SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication "
    "FROM pg_catalog.pg_roles WHERE rolname = current_user"
)
_ALEMBIC_VERSION_SQL = text("SELECT version_num FROM alembic_version")
_PUBLIC_TABLES_SQL = text(
    "SELECT tablename FROM pg_catalog.pg_tables "
    "WHERE schemaname = 'public'"
)
_TRY_LOCK_SQL = text("SELECT pg_try_advisory_lock(:lock_key)")
_UNLOCK_SQL = text("SELECT pg_advisory_unlock(:lock_key)")


class PostgreSQLIntegrationConfigurationError(RuntimeError):
    """Raised without including credentials or the raw database URL."""


class PostgreSQLIntegrationSafetyError(RuntimeError):
    """Raised when the connected target fails a safety invariant."""


@dataclass(frozen=True, slots=True)
class PostgreSQLIntegrationTarget:
    """Validated connection target; its URL is deliberately hidden in repr."""

    url: URL = field(repr=False)
    database: str = EXPECTED_DATABASE
    username: str = EXPECTED_USERNAME


@dataclass(frozen=True, slots=True)
class VerifiedPostgreSQLConnection:
    """Proof that one concrete SQLAlchemy connection passed preflight."""

    connection_identity: int
    database: str
    username: str
    postgresql_major: int


def integration_is_requested(environment: Mapping[str, str]) -> bool:
    """Return opt-in state, rejecting ambiguous values."""

    value = environment.get(OPT_IN_VARIABLE)
    if value is None or value == "":
        return False
    if value != "1":
        raise PostgreSQLIntegrationConfigurationError(
            f"{OPT_IN_VARIABLE} must be exactly 1 when integration tests are enabled."
        )
    return True


def load_integration_target(
    environment: Mapping[str, str],
) -> PostgreSQLIntegrationTarget:
    """Load and validate only the dedicated integration URL."""

    if not integration_is_requested(environment):
        raise PostgreSQLIntegrationConfigurationError(
            "PostgreSQL integration tests were not explicitly enabled."
        )
    raw_url = environment.get(DATABASE_URL_VARIABLE)
    if not raw_url:
        raise PostgreSQLIntegrationConfigurationError(
            f"{DATABASE_URL_VARIABLE} is required when integration tests are enabled."
        )
    try:
        url = make_url(raw_url)
    except (ArgumentError, TypeError, ValueError):
        raise PostgreSQLIntegrationConfigurationError(
            f"{DATABASE_URL_VARIABLE} is not a valid SQLAlchemy URL."
        ) from None

    if url.drivername != EXPECTED_DRIVER:
        raise PostgreSQLIntegrationConfigurationError(
            "The integration database driver is not allowed."
        )
    if url.database in FORBIDDEN_DATABASES:
        raise PostgreSQLIntegrationConfigurationError(
            "The configured database is explicitly forbidden for integration tests."
        )
    if url.database != EXPECTED_DATABASE:
        raise PostgreSQLIntegrationConfigurationError(
            "The integration database name is not allowed."
        )
    if url.username != EXPECTED_USERNAME:
        raise PostgreSQLIntegrationConfigurationError(
            "The integration database username is not allowed."
        )
    if url.host != EXPECTED_HOST:
        raise PostgreSQLIntegrationConfigurationError(
            "The integration database host is not allowed."
        )
    if url.port != EXPECTED_PORT:
        raise PostgreSQLIntegrationConfigurationError(
            "The integration database port is not allowed."
        )
    return PostgreSQLIntegrationTarget(url=url)


def reject_xdist(environment: Mapping[str, str]) -> None:
    """Prevent multiple pytest workers from sharing the destructive test DB."""

    if environment.get("PYTEST_XDIST_WORKER"):
        raise PostgreSQLIntegrationConfigurationError(
            "PostgreSQL integration tests cannot run under pytest-xdist."
        )


class PostgreSQLIntegrationHarness:
    """Validate, lock, inspect, and clean only the dedicated test database."""

    def __init__(self, target: PostgreSQLIntegrationTarget) -> None:
        self._target = target

    @property
    def target(self) -> PostgreSQLIntegrationTarget:
        return self._target

    def verify_connection(
        self,
        connection: Connection,
    ) -> VerifiedPostgreSQLConnection:
        """Verify server identity, PostgreSQL version, and role privileges."""

        try:
            identity = connection.execute(_IDENTITY_SQL).one()
            role = connection.execute(_ROLE_SQL).one_or_none()
        except SQLAlchemyError:
            raise PostgreSQLIntegrationSafetyError(
                "The PostgreSQL integration preflight query failed."
            ) from None

        database, username, version_number = identity
        if database in FORBIDDEN_DATABASES or database != EXPECTED_DATABASE:
            raise PostgreSQLIntegrationSafetyError(
                "The connected PostgreSQL database is not the isolated test database."
            )
        if username != EXPECTED_USERNAME:
            raise PostgreSQLIntegrationSafetyError(
                "The connected PostgreSQL role is not the isolated test role."
            )
        try:
            postgresql_major = int(version_number) // 10_000
        except (TypeError, ValueError):
            raise PostgreSQLIntegrationSafetyError(
                "The PostgreSQL server version could not be verified."
            ) from None
        if postgresql_major != EXPECTED_POSTGRESQL_MAJOR:
            raise PostgreSQLIntegrationSafetyError(
                "The PostgreSQL server major version is not supported by this test harness."
            )
        if role is None:
            raise PostgreSQLIntegrationSafetyError(
                "The PostgreSQL integration role could not be verified."
            )
        if any(value is not False for value in role):
            raise PostgreSQLIntegrationSafetyError(
                "The PostgreSQL integration role has forbidden elevated privileges."
            )
        return VerifiedPostgreSQLConnection(
            connection_identity=id(connection),
            database=database,
            username=username,
            postgresql_major=postgresql_major,
        )

    def verify_migrated_schema(
        self,
        connection: Connection,
        verification: VerifiedPostgreSQLConnection,
    ) -> None:
        """Require the expected Alembic head and exact application table set."""

        self._reverify_identity(connection, verification)
        try:
            revision = connection.execute(_ALEMBIC_VERSION_SQL).scalar_one()
            tables = {
                row[0] for row in connection.execute(_PUBLIC_TABLES_SQL).all()
            }
        except SQLAlchemyError:
            raise PostgreSQLIntegrationSafetyError(
                "The integration schema is missing or cannot be verified."
            ) from None
        expected_tables = set(APPLICATION_TABLES) | {"alembic_version"}
        if revision != EXPECTED_ALEMBIC_HEAD or tables != expected_tables:
            raise PostgreSQLIntegrationSafetyError(
                "The integration schema does not match the expected Alembic head."
            )

    def acquire_suite_lock(
        self,
        connection: Connection,
        verification: VerifiedPostgreSQLConnection,
    ) -> None:
        """Acquire one session advisory lock for the complete integration run."""

        self._reverify_identity(connection, verification)
        try:
            acquired = connection.execute(
                _TRY_LOCK_SQL,
                {"lock_key": SUITE_ADVISORY_LOCK_KEY},
            ).scalar_one()
        except SQLAlchemyError:
            raise PostgreSQLIntegrationSafetyError(
                "The PostgreSQL integration suite lock could not be acquired."
            ) from None
        if acquired is not True:
            raise PostgreSQLIntegrationSafetyError(
                "Another PostgreSQL integration test suite is already running."
            )

    def release_suite_lock(
        self,
        connection: Connection,
        verification: VerifiedPostgreSQLConnection,
    ) -> None:
        """Best-effort explicit unlock; closing the connection also releases it."""

        self._require_same_connection(connection, verification)
        try:
            connection.execute(
                _UNLOCK_SQL,
                {"lock_key": SUITE_ADVISORY_LOCK_KEY},
            )
        except SQLAlchemyError:
            return

    def cleanup_database(
        self,
        connection: Connection,
        verification: VerifiedPostgreSQLConnection,
    ) -> None:
        """Truncate only the fixed application-table allowlist."""

        self._reverify_identity(connection, verification)
        try:
            connection.execute(_CLEANUP_SQL)
        except SQLAlchemyError:
            raise PostgreSQLIntegrationSafetyError(
                "The isolated integration database could not be cleaned."
            ) from None

    def _reverify_identity(
        self,
        connection: Connection,
        verification: VerifiedPostgreSQLConnection,
    ) -> None:
        self._require_same_connection(connection, verification)
        try:
            database, username, version_number = connection.execute(
                _IDENTITY_SQL
            ).one()
            postgresql_major = int(version_number) // 10_000
        except (SQLAlchemyError, TypeError, ValueError):
            raise PostgreSQLIntegrationSafetyError(
                "The PostgreSQL integration target could not be reverified."
            ) from None
        if (
            database != verification.database
            or database != EXPECTED_DATABASE
            or username != verification.username
            or username != EXPECTED_USERNAME
            or postgresql_major != EXPECTED_POSTGRESQL_MAJOR
        ):
            raise PostgreSQLIntegrationSafetyError(
                "The PostgreSQL integration target changed after preflight."
            )

    @staticmethod
    def _require_same_connection(
        connection: Connection,
        verification: VerifiedPostgreSQLConnection,
    ) -> None:
        if verification.connection_identity != id(connection):
            raise PostgreSQLIntegrationSafetyError(
                "This PostgreSQL connection has not passed integration preflight."
            )


def safe_error_message(error: BaseException) -> str:
    """Return a fixed public diagnostic without exception or credential text."""

    if isinstance(
        error,
        (
            PostgreSQLIntegrationConfigurationError,
            PostgreSQLIntegrationSafetyError,
        ),
    ):
        return str(error)
    return "The PostgreSQL integration operation failed safely."

