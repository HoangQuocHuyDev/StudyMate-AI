"""Regression tests for versioned JWT revocation and atomic logout."""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from importlib import import_module
from pathlib import Path
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    select,
)
from sqlalchemy.orm import Session, sessionmaker

import app.routers.auth as auth_router
from app.core.security import create_access_token, decode_access_token
from app.db.session import get_db
from app.main import app
from app.models.user import User
from app.services.auth_service import StaleAccessTokenError, revoke_access_token


@pytest.fixture
def auth_session_factory(
    client: TestClient,
    tmp_path: Path,
) -> Iterator[sessionmaker[Session]]:
    """Provide an isolated file-backed database for real compare-and-swap SQL."""

    database_path = tmp_path / "token-revocation.sqlite3"
    engine = create_engine(
        f"sqlite+pysqlite:///{database_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    metadata = MetaData()
    Table(
        "users",
        metadata,
        Column("id", BigInteger, primary_key=True),
        Column("full_name", String(100), nullable=False),
        Column("username", String(30), nullable=False, unique=True),
        Column("password_hash", Text, nullable=False),
        Column("role", String(10), nullable=False),
        Column("is_active", Boolean, nullable=False),
        Column("token_version", Integer, nullable=False, server_default="0"),
        Column("created_at", DateTime(timezone=True), nullable=False),
    )
    metadata.create_all(engine)
    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )

    def override() -> Iterator[Session]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override
    yield factory
    app.dependency_overrides.pop(get_db, None)
    engine.dispose()


def add_user(
    factory: sessionmaker[Session],
    *,
    user_id: int,
    username: str,
    password_hash: str,
    token_version: int = 0,
) -> None:
    with factory() as session:
        session.add(
            User(
                id=user_id,
                full_name=f"User {user_id}",
                username=username,
                password_hash=password_hash,
                role="USER",
                is_active=True,
                token_version=token_version,
                created_at=datetime.now(timezone.utc),
            )
        )
        session.commit()


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_logout_revokes_current_token_and_returns_no_content(
    client: TestClient,
    auth_session_factory: sessionmaker[Session],
    stored_password_hash: str,
) -> None:
    add_user(
        auth_session_factory,
        user_id=1,
        username="logout_user",
        password_hash=stored_password_hash,
    )
    token = create_access_token(1, 0)

    response = client.post("/auth/logout", headers=bearer(token))

    assert response.status_code == 204
    assert response.content == b""
    assert client.get("/auth/me", headers=bearer(token)).status_code == 401


def test_login_after_logout_issues_a_valid_new_version(
    client: TestClient,
    auth_session_factory: sessionmaker[Session],
    stored_password_hash: str,
    plain_password: str,
) -> None:
    add_user(
        auth_session_factory,
        user_id=2,
        username="login_again",
        password_hash=stored_password_hash,
    )
    old_token = create_access_token(2, 0)
    assert client.post("/auth/logout", headers=bearer(old_token)).status_code == 204

    login_response = client.post(
        "/auth/login",
        json={"username": "login_again", "password": plain_password},
    )

    assert login_response.status_code == 200
    new_token = login_response.json()["access_token"]
    assert decode_access_token(new_token).token_version == 1
    assert client.get("/auth/me", headers=bearer(new_token)).status_code == 200


def test_logout_only_changes_the_authenticated_user_version(
    client: TestClient,
    auth_session_factory: sessionmaker[Session],
    stored_password_hash: str,
) -> None:
    add_user(
        auth_session_factory,
        user_id=3,
        username="first_user",
        password_hash=stored_password_hash,
    )
    add_user(
        auth_session_factory,
        user_id=4,
        username="second_user",
        password_hash=stored_password_hash,
    )

    response = client.post(
        "/auth/logout",
        headers=bearer(create_access_token(3, 0)),
    )

    assert response.status_code == 204
    with auth_session_factory() as session:
        versions = dict(session.execute(select(User.id, User.token_version)).all())
    assert versions == {3: 1, 4: 0}


def test_stale_compare_and_swap_is_reported_as_401(
    client: TestClient,
    auth_session_factory: sessionmaker[Session],
    stored_password_hash: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    add_user(
        auth_session_factory,
        user_id=5,
        username="stale_logout",
        password_hash=stored_password_hash,
    )

    def stale_revocation(*args: object, **kwargs: object) -> None:
        raise StaleAccessTokenError

    monkeypatch.setattr(auth_router, "revoke_access_token", stale_revocation)
    response = client.post(
        "/auth/logout",
        headers=bearer(create_access_token(5, 0)),
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_two_concurrent_revocations_cannot_both_update_the_same_version(
    auth_session_factory: sessionmaker[Session],
    stored_password_hash: str,
) -> None:
    add_user(
        auth_session_factory,
        user_id=6,
        username="concurrent_logout",
        password_hash=stored_password_hash,
    )
    barrier = Barrier(2)

    def revoke() -> str:
        with auth_session_factory() as session:
            barrier.wait(timeout=5)
            try:
                revoke_access_token(
                    session,
                    user_id=6,
                    expected_token_version=0,
                )
            except StaleAccessTokenError:
                return "stale"
            return "revoked"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: revoke(), range(2)))

    assert sorted(results) == ["revoked", "stale"]
    with auth_session_factory() as session:
        assert session.get(User, 6).token_version == 1


def test_token_version_model_and_migration_are_additive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    column = User.__table__.c.token_version
    assert isinstance(column.type, Integer)
    assert column.nullable is False
    assert str(column.server_default.arg) == "0"
    assert "ck_users_token_version_nonnegative" in {
        constraint.name for constraint in User.__table__.constraints
    }

    migration = import_module(
        "migrations.versions.c8f1a6d3e905_add_token_version_to_users"
    )

    class OperationRecorder:
        def __init__(self) -> None:
            self.columns: list[tuple[str, object]] = []
            self.checks: list[tuple[str, str, str]] = []
            self.dropped_constraints: list[tuple[str, str, str]] = []
            self.dropped_columns: list[tuple[str, str]] = []

        def add_column(self, table_name: str, added_column: object) -> None:
            self.columns.append((table_name, added_column))

        def create_check_constraint(
            self,
            name: str,
            table_name: str,
            condition: str,
        ) -> None:
            self.checks.append((name, table_name, condition))

        def drop_constraint(
            self,
            name: str,
            table_name: str,
            *,
            type_: str,
        ) -> None:
            self.dropped_constraints.append((name, table_name, type_))

        def drop_column(self, table_name: str, column_name: str) -> None:
            self.dropped_columns.append((table_name, column_name))

    recorder = OperationRecorder()
    monkeypatch.setattr(migration, "op", recorder)
    migration.upgrade()

    assert migration.revision == "c8f1a6d3e905"
    assert migration.down_revision == "b7d2e9f4c816"
    assert recorder.columns[0][0] == "users"
    assert recorder.columns[0][1].name == "token_version"
    assert recorder.columns[0][1].nullable is False
    assert str(recorder.columns[0][1].server_default.arg) == "0"
    assert recorder.checks == [
        (
            "ck_users_token_version_nonnegative",
            "users",
            "token_version >= 0",
        )
    ]

    migration.downgrade()
    assert recorder.dropped_constraints == [
        ("ck_users_token_version_nonnegative", "users", "check")
    ]
    assert recorder.dropped_columns == [("users", "token_version")]
