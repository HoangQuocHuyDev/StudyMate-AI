"""Shared fixtures and safeguards for isolated backend tests."""

import os
import sqlite3
from collections.abc import Callable, Iterator
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import Pool


# These values must be set before importing the application. Disabling dotenv
# guarantees that tests neither read nor use credentials from backend/.env.
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["DATABASE_URL"] = (
    "postgresql+psycopg://postgres:test-only-password@"
    "127.0.0.1:5432/studymate_ai_db"
)
os.environ["JWT_SECRET_KEY"] = (
    "test-only-jwt-secret-key-not-for-production-0123456789"
)
os.environ["JWT_ALGORITHM"] = "HS256"
os.environ["ACCESS_TOKEN_EXPIRE_MINUTES"] = "30"
os.environ["CORS_ORIGINS"] = (
    "http://localhost:5173,http://127.0.0.1:5173"
)


@event.listens_for(Pool, "connect")
def register_postgresql_text_functions_for_sqlite(
    dbapi_connection: object,
    connection_record: object,
) -> None:
    """Provide PostgreSQL text functions used by CHECK constraints in SQLite tests.

    Production constraints intentionally use PostgreSQL's ``btrim`` and
    ``char_length`` functions. Registering their equivalents once for every
    SQLite test connection keeps model metadata faithful to PostgreSQL without
    duplicating per-fixture compatibility listeners.
    """

    del connection_record
    if not isinstance(dbapi_connection, sqlite3.Connection):
        return

    dbapi_connection.create_function(
        "btrim",
        1,
        lambda value: value.strip() if value is not None else None,
    )
    dbapi_connection.create_function(
        "char_length",
        1,
        lambda value: len(value) if value is not None else None,
    )


from app.core.security import create_access_token, hash_password  # noqa: E402
from app.db.session import engine, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.auth_rate_limiter import (  # noqa: E402
    get_authentication_rate_limiter,
)


class FakeSession:
    """Small Session substitute covering the authentication data access API."""

    def __init__(
        self,
        *,
        scalar_result: object | None = None,
        get_result: User | None = None,
        scalar_error: SQLAlchemyError | None = None,
        get_error: SQLAlchemyError | None = None,
    ) -> None:
        self.scalar_result = scalar_result
        self.get_result = get_result
        self.scalar_error = scalar_error
        self.get_error = get_error
        self.added: User | None = None
        self.committed = False
        self.rollback_called = False

    def scalar(self, statement: object) -> object | None:
        if self.scalar_error is not None:
            raise self.scalar_error
        return self.scalar_result

    def get(self, model: type[User], identifier: int) -> User | None:
        if self.get_error is not None:
            raise self.get_error
        if self.get_result is not None and self.get_result.id == identifier:
            return self.get_result
        return None

    def add(self, user: User) -> None:
        self.added = user

    def flush(self) -> None:
        if self.added is None:
            raise AssertionError("No user was added before flush().")
        if self.added.id is None:
            self.added.id = 100
        if self.added.created_at is None:
            self.added.created_at = datetime.now(timezone.utc)

    def refresh(self, user: User) -> None:
        return None

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rollback_called = True


@pytest.fixture(autouse=True)
def block_real_database_connections(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail immediately if production code attempts a real DB connection."""

    def blocked_connect(*args: object, **kwargs: object) -> None:
        raise AssertionError("Tests must not connect to PostgreSQL.")

    monkeypatch.setattr(engine, "connect", blocked_connect)


@pytest.fixture(autouse=True)
def reset_authentication_rate_limiter() -> Iterator[None]:
    """Prevent process-local limiter state from leaking across tests."""

    limiter = get_authentication_rate_limiter()
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def fake_session_factory() -> type[FakeSession]:
    return FakeSession


@pytest.fixture
def override_db() -> Iterator[Callable[[FakeSession, FastAPI], None]]:
    touched_apps: list[FastAPI] = []

    def apply(session: FakeSession, target_app: FastAPI = app) -> None:
        def override() -> Iterator[FakeSession]:
            yield session

        target_app.dependency_overrides[get_db] = override
        touched_apps.append(target_app)

    yield apply

    for target_app in touched_apps:
        target_app.dependency_overrides.clear()


@pytest.fixture(scope="session")
def plain_password() -> str:
    return "ValidPassword123"


@pytest.fixture(scope="session")
def stored_password_hash(plain_password: str) -> str:
    return hash_password(plain_password)


@pytest.fixture
def user_factory(
    stored_password_hash: str,
) -> Callable[..., User]:
    def create_user(
        *,
        user_id: int = 42,
        username: str = "test_user",
        role: str = "USER",
        is_active: bool = True,
        token_version: int = 0,
    ) -> User:
        return User(
            id=user_id,
            full_name="Test User",
            username=username,
            password_hash=stored_password_hash,
            role=role,
            is_active=is_active,
            token_version=token_version,
            created_at=datetime.now(timezone.utc),
        )

    return create_user


@pytest.fixture
def active_user(user_factory: Callable[..., User]) -> User:
    return user_factory()


@pytest.fixture
def access_token(active_user: User) -> str:
    return create_access_token(active_user.id, active_user.token_version)
