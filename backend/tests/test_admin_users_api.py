"""Isolated API and service tests for administrator user management."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

import jwt
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
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.core.security import create_access_token
from app.db.session import get_db
from app.main import app
from app.models.user import User
from app.services.admin_users import (
    AdminUserUpdateError,
    _admin_lock_statement,
    update_admin_user_status,
)


UTC = timezone.utc


@pytest.fixture
def admin_users_session_factory(
    client: TestClient,
) -> Iterator[sessionmaker[Session]]:
    """Use an isolated SQLite database; never connect to PostgreSQL."""

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


def add_user(
    session: Session,
    *,
    user_id: int,
    username: str,
    role: str = "USER",
    is_active: bool = True,
    token_version: int = 0,
    created_at: datetime | None = None,
    password_hash: str = "test-only-hash",
) -> User:
    user = User(
        id=user_id,
        full_name=f"User {user_id}",
        username=username,
        password_hash=password_hash,
        role=role,
        is_active=is_active,
        token_version=token_version,
        created_at=created_at or datetime.now(UTC),
    )
    session.add(user)
    session.flush()
    return user


def auth_header(user: User, *, token_version: int | None = None) -> dict[str, str]:
    version = user.token_version if token_version is None else token_version
    token = create_access_token(user.id, version)
    return {"Authorization": f"Bearer {token}"}


def test_admin_users_requires_authentication_and_admin_role(
    client: TestClient,
    admin_users_session_factory: sessionmaker[Session],
) -> None:
    with admin_users_session_factory() as session:
        standard = add_user(session, user_id=1, username="standard")
        admin = add_user(session, user_id=2, username="admin", role="ADMIN")
        session.commit()

    assert client.get("/admin/users").status_code == 401
    assert client.get(
        "/admin/users",
        headers={"Authorization": "Bearer invalid"},
    ).status_code == 401
    assert client.get("/admin/users", headers=auth_header(standard)).status_code == 403
    assert client.get("/admin/users", headers=auth_header(admin)).status_code == 200
    assert client.patch(
        "/admin/users/1/status",
        json={"is_active": False},
    ).status_code == 401
    assert client.patch(
        "/admin/users/2/status",
        json={"is_active": False},
        headers=auth_header(standard),
    ).status_code == 403


def test_admin_users_rejects_inactive_stale_and_forged_admin_claims(
    client: TestClient,
    admin_users_session_factory: sessionmaker[Session],
) -> None:
    with admin_users_session_factory() as session:
        inactive = add_user(
            session,
            user_id=1,
            username="inactive",
            role="ADMIN",
            is_active=False,
        )
        admin = add_user(
            session,
            user_id=2,
            username="admin",
            role="ADMIN",
            token_version=3,
        )
        standard = add_user(session, user_id=3, username="standard")
        session.commit()

    assert client.get("/admin/users", headers=auth_header(inactive)).status_code == 401
    assert client.get(
        "/admin/users",
        headers=auth_header(admin, token_version=2),
    ).status_code == 401

    settings = get_settings()
    now = datetime.now(UTC)
    forged = jwt.encode(
        {
            "sub": str(standard.id),
            "iat": now,
            "exp": now + timedelta(minutes=30),
            "type": "access",
            "role": "ADMIN",
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "ver": standard.token_version,
        },
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    assert client.get(
        "/admin/users",
        headers={"Authorization": f"Bearer {forged}"},
    ).status_code == 403


def test_admin_user_list_search_filters_paginates_and_sorts(
    client: TestClient,
    admin_users_session_factory: sessionmaker[Session],
) -> None:
    base = datetime(2026, 10, 15, tzinfo=UTC)
    with admin_users_session_factory() as session:
        admin = add_user(
            session,
            user_id=1,
            username="admin",
            role="ADMIN",
            created_at=base - timedelta(days=3),
        )
        add_user(
            session,
            user_id=2,
            username="student_alpha",
            created_at=base - timedelta(days=2),
        )
        add_user(
            session,
            user_id=3,
            username="STUDENT_beta",
            is_active=False,
            created_at=base - timedelta(days=1),
        )
        add_user(
            session,
            user_id=4,
            username="latest_admin",
            role="ADMIN",
            created_at=base,
        )
        session.commit()

    response = client.get(
        "/admin/users?limit=2&offset=0",
        headers=auth_header(admin),
    )
    assert response.status_code == 200
    assert response.json()["total"] == 4
    assert [item["id"] for item in response.json()["items"]] == [4, 3]

    searched = client.get(
        "/admin/users?search=student&role=USER&is_active=false",
        headers=auth_header(admin),
    )
    assert searched.status_code == 200
    assert searched.json()["total"] == 1
    assert searched.json()["items"][0]["username"] == "STUDENT_beta"

    second_page = client.get(
        "/admin/users?limit=2&offset=2",
        headers=auth_header(admin),
    ).json()
    assert [item["id"] for item in second_page["items"]] == [2, 1]


def test_admin_user_search_treats_like_metacharacters_as_literals(
    client: TestClient,
    admin_users_session_factory: sessionmaker[Session],
) -> None:
    with admin_users_session_factory() as session:
        admin = add_user(session, user_id=1, username="admin", role="ADMIN")
        add_user(session, user_id=2, username="literal%name")
        add_user(session, user_id=3, username="literal_name")
        add_user(session, user_id=4, username=r"literal\name")
        add_user(session, user_id=5, username="literal.name")
        session.commit()

    for query, expected in (
        ("%", "literal%name"),
        ("_", "literal_name"),
        ("\\", r"literal\name"),
        (".", "literal.name"),
    ):
        response = client.get(
            "/admin/users",
            params={"search": query},
            headers=auth_header(admin),
        )
        assert response.status_code == 200
        assert [item["username"] for item in response.json()["items"]] == [expected]


def test_admin_user_list_never_exposes_authentication_fields(
    client: TestClient,
    admin_users_session_factory: sessionmaker[Session],
) -> None:
    with admin_users_session_factory() as session:
        admin = add_user(session, user_id=1, username="admin", role="ADMIN")
        add_user(session, user_id=2, username="user")
        session.commit()

    payload = client.get("/admin/users", headers=auth_header(admin)).json()
    assert set(payload) == {"items", "total", "limit", "offset"}
    assert set(payload["items"][0]) == {
        "id",
        "full_name",
        "username",
        "role",
        "is_active",
        "created_at",
    }
    serialized = str(payload)
    assert "password_hash" not in serialized
    assert "token_version" not in serialized


@pytest.mark.parametrize(
    "query",
    ["limit=0", "limit=101", "offset=-1", "role=OWNER", f"search={'x' * 256}"],
)
def test_admin_user_list_rejects_invalid_parameters(
    client: TestClient,
    admin_users_session_factory: sessionmaker[Session],
    query: str,
) -> None:
    with admin_users_session_factory() as session:
        admin = add_user(session, user_id=1, username="admin", role="ADMIN")
        session.commit()

    assert client.get(
        f"/admin/users?{query}",
        headers=auth_header(admin),
    ).status_code == 422


def test_admin_can_deactivate_and_reactivate_user_with_token_revocation(
    client: TestClient,
    admin_users_session_factory: sessionmaker[Session],
) -> None:
    with admin_users_session_factory() as session:
        admin = add_user(session, user_id=1, username="admin", role="ADMIN")
        target = add_user(session, user_id=2, username="target")
        session.commit()
    old_target_token = auth_header(target)

    deactivated = client.patch(
        "/admin/users/2/status",
        json={"is_active": False},
        headers=auth_header(admin),
    )
    assert deactivated.status_code == 200
    assert deactivated.json()["is_active"] is False
    assert client.get("/auth/me", headers=old_target_token).status_code == 401

    with admin_users_session_factory() as session:
        stored = session.get(User, 2)
        assert stored.is_active is False
        assert stored.token_version == 1

    reactivated = client.patch(
        "/admin/users/2/status",
        json={"is_active": True},
        headers=auth_header(admin),
    )
    assert reactivated.status_code == 200
    assert reactivated.json()["is_active"] is True
    with admin_users_session_factory() as session:
        stored = session.get(User, 2)
        assert stored.token_version == 2
        assert client.get(
            "/auth/me",
            headers=auth_header(stored),
        ).status_code == 200


def test_status_update_is_idempotent_and_rejects_extra_fields(
    client: TestClient,
    admin_users_session_factory: sessionmaker[Session],
) -> None:
    with admin_users_session_factory() as session:
        admin = add_user(session, user_id=1, username="admin", role="ADMIN")
        target = add_user(
            session,
            user_id=2,
            username="target",
            is_active=False,
            token_version=7,
        )
        session.commit()

    unchanged = client.patch(
        "/admin/users/2/status",
        json={"is_active": False},
        headers=auth_header(admin),
    )
    assert unchanged.status_code == 200
    with admin_users_session_factory() as session:
        assert session.get(User, target.id).token_version == 7

    invalid = client.patch(
        "/admin/users/2/status",
        json={"is_active": True, "role": "ADMIN"},
        headers=auth_header(admin),
    )
    assert invalid.status_code == 422
    assert client.patch(
        "/admin/users/2/status",
        json={"is_active": "true"},
        headers=auth_header(admin),
    ).status_code == 422


def test_admin_cannot_deactivate_self_or_remove_final_active_admin(
    client: TestClient,
    admin_users_session_factory: sessionmaker[Session],
) -> None:
    with admin_users_session_factory() as session:
        admin = add_user(session, user_id=1, username="admin", role="ADMIN")
        inactive_admin = add_user(
            session,
            user_id=2,
            username="inactive_admin",
            role="ADMIN",
            is_active=False,
        )
        session.commit()

    response = client.patch(
        "/admin/users/1/status",
        json={"is_active": False},
        headers=auth_header(admin),
    )
    assert response.status_code == 409
    with admin_users_session_factory() as session:
        assert session.get(User, admin.id).is_active is True
        assert session.get(User, inactive_admin.id).is_active is False


def test_status_update_handles_missing_user_and_preserves_unrelated_fields(
    client: TestClient,
    admin_users_session_factory: sessionmaker[Session],
) -> None:
    with admin_users_session_factory() as session:
        admin = add_user(session, user_id=1, username="admin", role="ADMIN")
        target = add_user(session, user_id=2, username="target")
        original = (target.username, target.role, target.password_hash, target.full_name)
        session.commit()

    assert client.patch(
        "/admin/users/999/status",
        json={"is_active": False},
        headers=auth_header(admin),
    ).status_code == 404
    assert client.patch(
        "/admin/users/2/status",
        json={"is_active": False},
        headers=auth_header(admin),
    ).status_code == 200

    with admin_users_session_factory() as session:
        stored = session.get(User, 2)
        assert (stored.username, stored.role, stored.password_hash, stored.full_name) == original


def test_status_update_rolls_back_when_commit_fails(
    admin_users_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with admin_users_session_factory() as setup:
        add_user(setup, user_id=1, username="admin", role="ADMIN")
        add_user(setup, user_id=2, username="target")
        setup.commit()

    with admin_users_session_factory() as session:
        def fail_commit() -> None:
            raise SQLAlchemyError("safe test failure")

        monkeypatch.setattr(session, "commit", fail_commit)
        with pytest.raises(AdminUserUpdateError):
            update_admin_user_status(
                session,
                actor_id=1,
                expected_actor_token_version=0,
                target_user_id=2,
                is_active=False,
            )

    with admin_users_session_factory() as verification:
        target = verification.get(User, 2)
        assert target.is_active is True
        assert target.token_version == 0


def test_postgresql_admin_lock_statement_has_deterministic_for_update_order() -> None:
    sql = str(
        _admin_lock_statement().compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "WHERE users.role = 'ADMIN'" in sql
    assert "ORDER BY users.id ASC" in sql
    assert sql.endswith("FOR UPDATE")


@pytest.mark.skip(
    reason=(
        "Requires an explicitly provisioned isolated PostgreSQL test database; "
        "SQLite cannot verify cross-session FOR UPDATE serialization."
    )
)
def test_concurrent_admin_status_updates_are_serialized_by_postgresql() -> None:
    """Reserved for the isolated PostgreSQL integration environment."""

