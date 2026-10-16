"""Isolated tests for authenticated account Settings endpoints."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone

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
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token, hash_password, verify_password
from app.db.session import get_db
from app.main import app
from app.models.user import User
from app.services.auth_service import PasswordChangeError, change_current_user_password


@pytest.fixture
def settings_session_factory(client: TestClient) -> Iterator[sessionmaker[Session]]:
    """Use an isolated in-memory database without production connectivity."""

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    metadata = MetaData()
    Table(
        "users",
        metadata,
        Column("id", BigInteger, primary_key=True),
        Column("full_name", String(100), nullable=False),
        Column("username", String(30), nullable=False),
        Column("password_hash", Text, nullable=False),
        Column("role", String(10), nullable=False),
        Column("is_active", Boolean, nullable=False),
        Column("token_version", Integer, nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
    )
    metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override() -> Iterator[Session]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override
    yield factory
    app.dependency_overrides.pop(get_db, None)
    engine.dispose()


def add_account(session: Session, *, password: str = "CurrentPass123") -> User:
    user = User(
        id=1,
        full_name="Nguyễn Văn A",
        username="student_one",
        password_hash=hash_password(password),
        role="USER",
        is_active=True,
        token_version=0,
        created_at=datetime.now(timezone.utc),
    )
    session.add(user)
    session.commit()
    return user


def authorization(user: User, *, version: int | None = None) -> dict[str, str]:
    token = create_access_token(
        user.id,
        user.token_version if version is None else version,
    )
    return {"Authorization": f"Bearer {token}"}


def test_profile_update_changes_only_full_name(
    client: TestClient,
    settings_session_factory: sessionmaker[Session],
) -> None:
    with settings_session_factory() as session:
        user = add_account(session)
        old_hash = user.password_hash
        headers = authorization(user)

    response = client.patch(
        "/auth/me",
        json={"full_name": "  Nguyễn Thị B  "},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["full_name"] == "Nguyễn Thị B"
    assert response.json()["username"] == "student_one"
    assert "password_hash" not in response.json()
    assert "token_version" not in response.json()
    with settings_session_factory() as session:
        stored = session.get(User, 1)
        assert stored is not None
        assert stored.full_name == "Nguyễn Thị B"
        assert stored.password_hash == old_hash
        assert stored.token_version == 0


@pytest.mark.parametrize("full_name", ["", " ", "A", "A" * 101])
def test_profile_update_validates_name(
    client: TestClient,
    settings_session_factory: sessionmaker[Session],
    full_name: str,
) -> None:
    with settings_session_factory() as session:
        headers = authorization(add_account(session))

    response = client.patch("/auth/me", json={"full_name": full_name}, headers=headers)
    assert response.status_code == 422


def test_password_change_rejects_wrong_current_password_without_mutation(
    client: TestClient,
    settings_session_factory: sessionmaker[Session],
) -> None:
    with settings_session_factory() as session:
        user = add_account(session)
        old_hash = user.password_hash
        headers = authorization(user)

    response = client.post(
        "/auth/change-password",
        json={
            "current_password": "WrongPass123",
            "new_password": "NewPassword456",
            "confirm_new_password": "NewPassword456",
        },
        headers=headers,
    )

    assert response.status_code == 400
    with settings_session_factory() as session:
        stored = session.get(User, 1)
        assert stored is not None
        assert stored.password_hash == old_hash
        assert stored.token_version == 0


def test_password_change_uses_argon2_and_revokes_old_jwt(
    client: TestClient,
    settings_session_factory: sessionmaker[Session],
) -> None:
    with settings_session_factory() as session:
        user = add_account(session)
        headers = authorization(user)

    response = client.post(
        "/auth/change-password",
        json={
            "current_password": "CurrentPass123",
            "new_password": "NewPassword456",
            "confirm_new_password": "NewPassword456",
        },
        headers=headers,
    )

    assert response.status_code == 204
    assert response.content == b""
    assert client.get("/auth/me", headers=headers).status_code == 401
    with settings_session_factory() as session:
        stored = session.get(User, 1)
        assert stored is not None
        assert stored.token_version == 1
        assert stored.password_hash.startswith("$argon2")
        assert verify_password("NewPassword456", stored.password_hash)
        assert not verify_password("CurrentPass123", stored.password_hash)

    login_response = client.post(
        "/auth/login",
        json={"username": "student_one", "password": "NewPassword456"},
    )
    assert login_response.status_code == 200
    new_headers = {
        "Authorization": f"Bearer {login_response.json()['access_token']}"
    }
    assert client.get("/auth/me", headers=new_headers).status_code == 200


@pytest.mark.parametrize(
    "payload",
    [
        {
            "current_password": "CurrentPass123",
            "new_password": "letters-only",
            "confirm_new_password": "letters-only",
        },
        {
            "current_password": "CurrentPass123",
            "new_password": "NewPassword456",
            "confirm_new_password": "Different789",
        },
        {
            "current_password": "CurrentPass123",
            "new_password": "CurrentPass123",
            "confirm_new_password": "CurrentPass123",
        },
    ],
)
def test_password_change_validates_policy_and_confirmation(
    client: TestClient,
    settings_session_factory: sessionmaker[Session],
    payload: dict[str, str],
) -> None:
    with settings_session_factory() as session:
        headers = authorization(add_account(session))

    assert client.post(
        "/auth/change-password",
        json=payload,
        headers=headers,
    ).status_code == 422


def test_settings_endpoints_require_authentication(client: TestClient) -> None:
    assert client.patch("/auth/me", json={"full_name": "Valid Name"}).status_code == 401
    assert client.post(
        "/auth/change-password",
        json={
            "current_password": "CurrentPass123",
            "new_password": "NewPassword456",
            "confirm_new_password": "NewPassword456",
        },
    ).status_code == 401


class FailingSession:
    def execute(self, statement: object) -> None:
        del statement
        raise SQLAlchemyError("private database detail")

    def rollback(self) -> None:
        return None


def test_password_change_rolls_back_provider_details(
    settings_session_factory: sessionmaker[Session],
) -> None:
    from app.schemas.user import UserPasswordChange

    with settings_session_factory() as session:
        user = add_account(session)
        session.expunge(user)

    with pytest.raises(PasswordChangeError) as caught:
        change_current_user_password(
            FailingSession(),  # type: ignore[arg-type]
            user=user,
            expected_token_version=0,
            password_change=UserPasswordChange(
                current_password="CurrentPass123",
                new_password="NewPassword456",
                confirm_new_password="NewPassword456",
            ),
        )
    assert "private database detail" not in str(caught.value)
