"""Cross-process capacity tests for synchronous RAG Chat."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from sqlalchemy.exc import OperationalError

from app.services.summary.concurrency import (
    PostgreSQLCapacityConcurrencyCoordinator,
    SummaryConcurrencyError,
    SummaryConcurrencyLimitError,
    SummaryConcurrencyLimits,
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

    def connect(self) -> FakeConnection:
        return FakeConnection(self.server)


class FailingEngine:
    def connect(self) -> None:
        raise OperationalError("connect", {}, Exception("unavailable"))


def coordinator(
    server: FakeAdvisoryLockServer,
    *,
    namespace: str = "chat",
    global_limit: int = 2,
    per_user_limit: int = 1,
) -> PostgreSQLCapacityConcurrencyCoordinator:
    return PostgreSQLCapacityConcurrencyCoordinator(  # type: ignore[arg-type]
        FakeEngine(server),
        SummaryConcurrencyLimits(global_limit, per_user_limit),
        namespace=namespace,
    )


def test_same_user_limit_is_shared_between_coordinator_instances() -> None:
    server = FakeAdvisoryLockServer()
    first = coordinator(server)
    second = coordinator(server)

    with first.capacity(7):
        with pytest.raises(SummaryConcurrencyLimitError):
            with second.capacity(7):
                raise AssertionError("same user must not acquire a second slot")

        # A different user can use the remaining global slot.
        with second.capacity(8):
            pass

    assert server.held == set()


def test_global_limit_is_shared_between_users_and_process_simulations() -> None:
    server = FakeAdvisoryLockServer()
    first_process = coordinator(server, global_limit=1)
    second_process = coordinator(server, global_limit=1)

    with first_process.capacity(7):
        with pytest.raises(SummaryConcurrencyLimitError):
            with second_process.capacity(8):
                raise AssertionError("global capacity must be exhausted")

    with second_process.capacity(8):
        pass
    assert server.held == set()


def test_capacity_is_released_after_failure_and_retry_succeeds() -> None:
    server = FakeAdvisoryLockServer()
    first = coordinator(server, global_limit=1)
    second = coordinator(server, global_limit=1)

    with pytest.raises(RuntimeError):
        with first.capacity(7):
            raise RuntimeError("provider failed")

    with second.capacity(7):
        pass
    assert server.held == set()


def test_chat_and_summary_capacity_namespaces_do_not_interfere() -> None:
    server = FakeAdvisoryLockServer()
    chat = coordinator(server, namespace="chat", global_limit=1)
    summary = coordinator(server, namespace="summary", global_limit=1)

    with chat.capacity(7):
        with summary.capacity(7):
            pass
    assert server.held == set()


def test_database_connection_failure_is_a_coordination_error() -> None:
    coordinator = PostgreSQLCapacityConcurrencyCoordinator(  # type: ignore[arg-type]
        FailingEngine(),
        SummaryConcurrencyLimits(1, 1),
        namespace="chat",
    )

    with pytest.raises(SummaryConcurrencyError):
        with coordinator.capacity(7):
            raise AssertionError("capacity must not be entered")
