"""Tests for PostgreSQL advisory-lock summary coordination."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from app.services.summary.concurrency import (
    PostgreSQLSummaryConcurrencyCoordinator,
    SummaryConcurrencyLimitError,
    SummaryConcurrencyLimits,
    SummaryGenerationBusyError,
)


@dataclass
class FakeAdvisoryLockServer:
    held: set[int] = field(default_factory=set)


class FakeConnection:
    def __init__(self, server: FakeAdvisoryLockServer) -> None:
        self.server = server
        self.owned: set[int] = set()
        self.closed = False
        self.invalidated = False

    def execution_options(self, **options: object) -> FakeConnection:
        assert options == {"isolation_level": "AUTOCOMMIT"}
        return self

    def scalar(self, statement: object, parameters: dict[str, int]) -> bool:
        sql = str(statement)
        key = parameters["lock_key"]
        if "pg_try_advisory_lock" in sql:
            if key in self.server.held:
                return False
            self.server.held.add(key)
            self.owned.add(key)
            return True
        if "pg_advisory_unlock" in sql:
            if key not in self.owned:
                return False
            self.owned.remove(key)
            self.server.held.remove(key)
            return True
        raise AssertionError(f"Unexpected SQL: {sql}")

    def invalidate(self) -> None:
        self.invalidated = True
        self._release_all()

    def close(self) -> None:
        self.closed = True
        self._release_all()

    def _release_all(self) -> None:
        self.server.held.difference_update(self.owned)
        self.owned.clear()


class FakeEngine:
    def __init__(self, server: FakeAdvisoryLockServer) -> None:
        self.server = server
        self.connections: list[FakeConnection] = []

    def connect(self) -> FakeConnection:
        connection = FakeConnection(self.server)
        self.connections.append(connection)
        return connection


def coordinator(
    server: FakeAdvisoryLockServer,
    *,
    global_limit: int = 2,
    per_user_limit: int = 1,
) -> PostgreSQLSummaryConcurrencyCoordinator:
    return PostgreSQLSummaryConcurrencyCoordinator(  # type: ignore[arg-type]
        FakeEngine(server),
        SummaryConcurrencyLimits(global_limit, per_user_limit),
    )


def test_postgresql_deduplication_is_shared_between_coordinators() -> None:
    server = FakeAdvisoryLockServer()
    first = coordinator(server)
    second = coordinator(server)

    with first.deduplicate(9, "STANDARD"):
        with pytest.raises(SummaryGenerationBusyError):
            with second.deduplicate(9, "STANDARD"):
                raise AssertionError("duplicate lock must not be acquired")

    with second.deduplicate(9, "STANDARD"):
        pass
    assert server.held == set()


def test_postgresql_global_slots_are_shared_between_users() -> None:
    server = FakeAdvisoryLockServer()
    first = coordinator(server, global_limit=1)
    second = coordinator(server, global_limit=1)

    with first.deduplicate(1, "SHORT") as first_lease:
        with first_lease.capacity(7):
            with second.deduplicate(2, "SHORT") as second_lease:
                with pytest.raises(SummaryConcurrencyLimitError):
                    with second_lease.capacity(8):
                        raise AssertionError("global capacity must be exhausted")
    assert server.held == set()


def test_postgresql_user_slots_are_shared_across_documents() -> None:
    server = FakeAdvisoryLockServer()
    first = coordinator(server, global_limit=2, per_user_limit=1)
    second = coordinator(server, global_limit=2, per_user_limit=1)

    with first.deduplicate(1, "SHORT") as first_lease:
        with first_lease.capacity(7):
            with second.deduplicate(2, "DETAILED") as second_lease:
                with pytest.raises(SummaryConcurrencyLimitError):
                    with second_lease.capacity(7):
                        raise AssertionError("user capacity must be exhausted")
    assert server.held == set()


def test_postgresql_locks_are_released_when_generation_fails() -> None:
    server = FakeAdvisoryLockServer()
    first = coordinator(server, global_limit=1)
    second = coordinator(server, global_limit=1)

    with pytest.raises(RuntimeError):
        with first.deduplicate(1, "STANDARD") as lease:
            with lease.capacity(7):
                raise RuntimeError("provider failed")

    with second.deduplicate(1, "STANDARD") as lease:
        with lease.capacity(7):
            pass
    assert server.held == set()


@pytest.mark.parametrize(
    "limits",
    [
        SummaryConcurrencyLimits(0, 1),
        SummaryConcurrencyLimits(1, 0),
        SummaryConcurrencyLimits(1, 2),
    ],
)
def test_invalid_concurrency_limits_are_rejected(
    limits: SummaryConcurrencyLimits,
) -> None:
    with pytest.raises(Exception):
        limits.validate()
