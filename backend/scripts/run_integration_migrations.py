"""Manually apply Alembic migrations to the verified integration database.

This script is opt-in and is never called by pytest.  It does not read the
application ``DATABASE_URL`` and does not create or drop a database or role.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from scripts.postgresql_integration import (
    PostgreSQLIntegrationHarness,
    load_integration_target,
    reject_xdist,
    safe_error_message,
)


BACKEND_DIR = Path(__file__).resolve().parents[1]


def run() -> int:
    """Validate the target, then upgrade only that existing test database."""

    engine = None
    lock_connection = None
    try:
        reject_xdist(os.environ)
        target = load_integration_target(os.environ)
        harness = PostgreSQLIntegrationHarness(target)
        engine = create_engine(target.url, poolclass=NullPool)

        lock_connection = engine.connect().execution_options(
            isolation_level="AUTOCOMMIT"
        )
        lock_verification = harness.verify_connection(lock_connection)
        harness.acquire_suite_lock(lock_connection, lock_verification)

        with engine.connect() as migration_connection:
            migration_verification = harness.verify_connection(
                migration_connection
            )
            migration_connection.rollback()
            alembic_config = Config(str(BACKEND_DIR / "alembic.ini"))
            alembic_config.attributes["validated_integration_connection"] = (
                migration_connection
            )
            command.upgrade(alembic_config, "head")
            harness.verify_migrated_schema(
                migration_connection,
                migration_verification,
            )
        return 0
    except Exception as error:
        print(safe_error_message(error), file=sys.stderr)
        return 1
    finally:
        if lock_connection is not None:
            lock_connection.close()
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(run())
