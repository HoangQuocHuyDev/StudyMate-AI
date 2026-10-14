"""Cross-process concurrency controls for document summary generation.

PostgreSQL session advisory locks are used in production so coordination is
shared by every application process without requiring another table.  SQLite
uses a process-local implementation for isolated tests only.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
from threading import BoundedSemaphore, Lock
from typing import Protocol
from weakref import WeakKeyDictionary

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session


DEFAULT_SUMMARY_GLOBAL_CONCURRENCY = 4
DEFAULT_SUMMARY_USER_CONCURRENCY = 1


class SummaryConcurrencyError(Exception):
    """Base class for safe summary coordination failures."""


class SummaryGenerationBusyError(SummaryConcurrencyError):
    """The same document and summary type are already being generated."""


class SummaryConcurrencyLimitError(SummaryConcurrencyError):
    """No global or per-user summary execution slot is available."""


class SummaryConcurrencyConfigurationError(SummaryConcurrencyError):
    """The database cannot provide the required coordination semantics."""


@dataclass(frozen=True, slots=True)
class SummaryConcurrencyLimits:
    global_limit: int = DEFAULT_SUMMARY_GLOBAL_CONCURRENCY
    per_user_limit: int = DEFAULT_SUMMARY_USER_CONCURRENCY

    def validate(self) -> None:
        for value in (self.global_limit, self.per_user_limit):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise SummaryConcurrencyConfigurationError(
                    "Summary concurrency limits must be positive integers."
                )
        if self.per_user_limit > self.global_limit:
            raise SummaryConcurrencyConfigurationError(
                "Per-user summary concurrency cannot exceed the global limit."
            )


class SummaryGenerationLease(Protocol):
    @contextmanager
    def capacity(self, user_id: int) -> Iterator[None]:
        """Claim one global and one user-scoped execution slot."""


class SummaryConcurrencyCoordinator(Protocol):
    @contextmanager
    def deduplicate(
        self,
        document_id: int,
        summary_type: str,
    ) -> Iterator[SummaryGenerationLease]:
        """Claim the unique generation key without waiting indefinitely."""


class CapacityConcurrencyCoordinator(Protocol):
    """Cross-process execution capacity without request deduplication."""

    @contextmanager
    def capacity(self, user_id: int) -> Iterator[None]:
        """Claim one global and one user-scoped execution slot."""


def get_summary_concurrency_coordinator(
    db: Session,
    limits: SummaryConcurrencyLimits | None = None,
) -> SummaryConcurrencyCoordinator:
    """Return one coordinator shared for the session's SQLAlchemy engine."""

    active_limits = limits or SummaryConcurrencyLimits()
    active_limits.validate()
    bind = db.get_bind()
    engine = bind if isinstance(bind, Engine) else bind.engine
    dialect_name = engine.dialect.name
    if dialect_name == "postgresql":
        return _get_cached_coordinator(
            engine,
            active_limits,
            PostgreSQLSummaryConcurrencyCoordinator,
        )
    if dialect_name == "sqlite":
        return _get_cached_coordinator(
            engine,
            active_limits,
            InProcessSummaryConcurrencyCoordinator,
        )
    raise SummaryConcurrencyConfigurationError(
        "Summary concurrency requires PostgreSQL."
    )


_coordinator_cache_lock = Lock()
_coordinator_cache: WeakKeyDictionary[
    Engine,
    dict[SummaryConcurrencyLimits, SummaryConcurrencyCoordinator],
] = WeakKeyDictionary()
_capacity_coordinator_cache: WeakKeyDictionary[
    Engine,
    dict[tuple[str, SummaryConcurrencyLimits], CapacityConcurrencyCoordinator],
] = WeakKeyDictionary()


def get_capacity_concurrency_coordinator(
    db: Session,
    *,
    namespace: str,
    limits: SummaryConcurrencyLimits,
) -> CapacityConcurrencyCoordinator:
    """Return a namespaced capacity coordinator for one SQLAlchemy engine."""

    limits.validate()
    if not namespace or namespace != namespace.strip():
        raise SummaryConcurrencyConfigurationError(
            "Concurrency namespace must be a non-empty trimmed value."
        )
    bind = db.get_bind()
    engine = bind if isinstance(bind, Engine) else bind.engine
    cache_key = (namespace, limits)
    with _coordinator_cache_lock:
        by_key = _capacity_coordinator_cache.setdefault(engine, {})
        coordinator = by_key.get(cache_key)
        if coordinator is not None:
            return coordinator
        if engine.dialect.name == "postgresql":
            coordinator = PostgreSQLCapacityConcurrencyCoordinator(
                engine,
                limits,
                namespace=namespace,
            )
        elif engine.dialect.name == "sqlite":
            coordinator = InProcessCapacityConcurrencyCoordinator(
                engine,
                limits,
            )
        else:
            raise SummaryConcurrencyConfigurationError(
                "Concurrency capacity requires PostgreSQL."
            )
        by_key[cache_key] = coordinator
        return coordinator


def _get_cached_coordinator(
    engine: Engine,
    limits: SummaryConcurrencyLimits,
    coordinator_type: type[PostgreSQLSummaryConcurrencyCoordinator]
    | type[InProcessSummaryConcurrencyCoordinator],
) -> SummaryConcurrencyCoordinator:
    with _coordinator_cache_lock:
        by_limits = _coordinator_cache.setdefault(engine, {})
        coordinator = by_limits.get(limits)
        if coordinator is None:
            coordinator = coordinator_type(engine, limits)
            by_limits[limits] = coordinator
        return coordinator


class PostgreSQLSummaryConcurrencyCoordinator:
    """Multi-process coordinator backed by PostgreSQL session advisory locks."""

    def __init__(self, engine: Engine, limits: SummaryConcurrencyLimits) -> None:
        limits.validate()
        self._engine = engine
        self._limits = limits

    @contextmanager
    def deduplicate(
        self,
        document_id: int,
        summary_type: str,
    ) -> Iterator[SummaryGenerationLease]:
        try:
            connection = self._engine.connect().execution_options(
                isolation_level="AUTOCOMMIT"
            )
        except SQLAlchemyError:
            raise SummaryConcurrencyError(
                "Summary concurrency storage is unavailable."
            ) from None
        lease = _PostgreSQLGenerationLease(
            connection,
            self._limits,
            namespace="summary",
        )
        key = _advisory_key(f"summary:dedupe:{document_id}:{summary_type}")
        try:
            try:
                acquired = lease.try_acquire(key)
            except SQLAlchemyError:
                raise SummaryConcurrencyError(
                    "Summary concurrency storage is unavailable."
                ) from None
            if not acquired:
                raise SummaryGenerationBusyError(
                    "This document summary is already being generated."
                )
            yield lease
        finally:
            lease.close()


class _PostgreSQLGenerationLease:
    def __init__(
        self,
        connection: Connection,
        limits: SummaryConcurrencyLimits,
        *,
        namespace: str,
    ) -> None:
        self._connection = connection
        self._limits = limits
        self._namespace = namespace
        self._held_keys: list[int] = []
        self._closed = False

    def try_acquire(self, key: int) -> bool:
        acquired = bool(
            self._connection.scalar(
                text("SELECT pg_try_advisory_lock(:lock_key)"),
                {"lock_key": key},
            )
        )
        if acquired:
            self._held_keys.append(key)
        return acquired

    @contextmanager
    def capacity(self, user_id: int) -> Iterator[None]:
        try:
            global_key = self._try_slot("global", 0, self._limits.global_limit)
        except SQLAlchemyError:
            self._invalidate()
            raise SummaryConcurrencyError(
                "Summary concurrency storage is unavailable."
            ) from None
        if global_key is None:
            raise SummaryConcurrencyLimitError(
                "The global summary concurrency limit is reached."
            )
        try:
            user_key = self._try_slot(
                "user", user_id, self._limits.per_user_limit
            )
        except SQLAlchemyError:
            self._invalidate()
            raise SummaryConcurrencyError(
                "Summary concurrency storage is unavailable."
            ) from None
        if user_key is None:
            self._release_key(global_key)
            raise SummaryConcurrencyLimitError(
                "The per-user summary concurrency limit is reached."
            )
        try:
            yield
        finally:
            self._release_key(user_key)
            self._release_key(global_key)

    def _try_slot(self, scope: str, owner: int, count: int) -> int | None:
        for slot in range(count):
            key = _advisory_key(
                f"{self._namespace}:capacity:{scope}:{owner}:{slot}"
            )
            if self.try_acquire(key):
                return key
        return None

    def _release_key(self, key: int) -> None:
        if key not in self._held_keys:
            return
        try:
            released = bool(
                self._connection.scalar(
                    text("SELECT pg_advisory_unlock(:lock_key)"),
                    {"lock_key": key},
                )
            )
            if not released:
                raise RuntimeError("Advisory lock ownership was lost.")
            self._held_keys.remove(key)
        except Exception:
            self._invalidate()
            raise SummaryConcurrencyError(
                "Summary concurrency resources could not be released."
            ) from None

    def close(self) -> None:
        if self._closed:
            return
        try:
            for key in tuple(reversed(self._held_keys)):
                self._release_key(key)
        finally:
            try:
                self._connection.close()
            finally:
                self._closed = True

    def _invalidate(self) -> None:
        try:
            self._connection.invalidate()
        finally:
            self._held_keys.clear()


class InProcessSummaryConcurrencyCoordinator:
    """SQLite-only test coordinator; it is not a production fallback."""

    def __init__(self, engine: Engine, limits: SummaryConcurrencyLimits) -> None:
        del engine
        limits.validate()
        self._limits = limits
        self._global_slots = BoundedSemaphore(limits.global_limit)
        self._state_lock = Lock()
        self._dedupe: dict[tuple[int, str], Lock] = {}
        self._dedupe_refs: dict[tuple[int, str], int] = {}
        self._user_slots: dict[int, BoundedSemaphore] = {}
        self._user_refs: dict[int, int] = {}

    @contextmanager
    def deduplicate(
        self,
        document_id: int,
        summary_type: str,
    ) -> Iterator[SummaryGenerationLease]:
        key = (document_id, summary_type)
        with self._state_lock:
            lock = self._dedupe.setdefault(key, Lock())
            self._dedupe_refs[key] = self._dedupe_refs.get(key, 0) + 1
        acquired = lock.acquire(blocking=False)
        try:
            if not acquired:
                raise SummaryGenerationBusyError(
                    "This document summary is already being generated."
                )
            yield _InProcessGenerationLease(self, self._limits)
        finally:
            if acquired:
                lock.release()
            with self._state_lock:
                remaining = self._dedupe_refs[key] - 1
                if remaining == 0 and not lock.locked():
                    self._dedupe_refs.pop(key, None)
                    self._dedupe.pop(key, None)
                else:
                    self._dedupe_refs[key] = remaining

    @contextmanager
    def capacity(self, user_id: int) -> Iterator[None]:
        """Claim capacity directly for operations that are not deduplicated."""

        with _InProcessGenerationLease(self, self._limits).capacity(user_id):
            yield

    def _acquire_user_slot(self, user_id: int) -> BoundedSemaphore | None:
        with self._state_lock:
            semaphore = self._user_slots.setdefault(
                user_id,
                BoundedSemaphore(self._limits.per_user_limit),
            )
            self._user_refs[user_id] = self._user_refs.get(user_id, 0) + 1
        if semaphore.acquire(blocking=False):
            return semaphore
        self._release_user_reference(user_id)
        return None

    def _release_user_slot(
        self,
        user_id: int,
        semaphore: BoundedSemaphore,
    ) -> None:
        semaphore.release()
        self._release_user_reference(user_id)

    def _release_user_reference(self, user_id: int) -> None:
        with self._state_lock:
            remaining = self._user_refs[user_id] - 1
            if remaining == 0:
                self._user_refs.pop(user_id, None)
                self._user_slots.pop(user_id, None)
            else:
                self._user_refs[user_id] = remaining


class _InProcessGenerationLease:
    def __init__(
        self,
        coordinator: InProcessSummaryConcurrencyCoordinator,
        limits: SummaryConcurrencyLimits,
    ) -> None:
        self._coordinator = coordinator
        self._limits = limits

    @contextmanager
    def capacity(self, user_id: int) -> Iterator[None]:
        del self._limits
        if not self._coordinator._global_slots.acquire(blocking=False):
            raise SummaryConcurrencyLimitError(
                "The global summary concurrency limit is reached."
            )
        user_slot = self._coordinator._acquire_user_slot(user_id)
        if user_slot is None:
            self._coordinator._global_slots.release()
            raise SummaryConcurrencyLimitError(
                "The per-user summary concurrency limit is reached."
            )
        try:
            yield
        finally:
            self._coordinator._release_user_slot(user_id, user_slot)
            self._coordinator._global_slots.release()


class PostgreSQLCapacityConcurrencyCoordinator:
    """Namespaced multi-process capacity backed by PostgreSQL locks."""

    def __init__(
        self,
        engine: Engine,
        limits: SummaryConcurrencyLimits,
        *,
        namespace: str,
    ) -> None:
        limits.validate()
        self._engine = engine
        self._limits = limits
        self._namespace = namespace

    @contextmanager
    def capacity(self, user_id: int) -> Iterator[None]:
        try:
            connection = self._engine.connect().execution_options(
                isolation_level="AUTOCOMMIT"
            )
        except SQLAlchemyError:
            raise SummaryConcurrencyError(
                "Concurrency storage is unavailable."
            ) from None
        lease = _PostgreSQLGenerationLease(
            connection,
            self._limits,
            namespace=self._namespace,
        )
        try:
            with lease.capacity(user_id):
                yield
        finally:
            lease.close()


class InProcessCapacityConcurrencyCoordinator:
    """SQLite-only capacity coordinator used by isolated tests."""

    def __init__(self, engine: Engine, limits: SummaryConcurrencyLimits) -> None:
        self._delegate = InProcessSummaryConcurrencyCoordinator(engine, limits)

    @contextmanager
    def capacity(self, user_id: int) -> Iterator[None]:
        with self._delegate.capacity(user_id):
            yield


def _advisory_key(namespace: str) -> int:
    """Return a deterministic signed int64 key without exposing source IDs."""

    raw = int.from_bytes(
        sha256(namespace.encode("utf-8")).digest()[:8],
        byteorder="big",
        signed=False,
    )
    return raw if raw < 2**63 else raw - 2**64
