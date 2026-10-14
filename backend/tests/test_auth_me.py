"""Tests for GET /auth/me."""

from datetime import datetime, timedelta, timezone

import jwt
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.core.security import create_access_token


def test_auth_me_returns_current_user_without_password_hash(
    client,
    override_db,
    fake_session_factory,
    active_user,
    access_token,
) -> None:
    override_db(fake_session_factory(get_result=active_user))

    response = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    assert response.status_code == 200
    assert response.json()["id"] == active_user.id
    assert response.json()["username"] == active_user.username
    assert response.json()["role"] == active_user.role
    assert "password_hash" not in response.json()


def test_auth_me_without_token_returns_401(client, override_db, fake_session_factory) -> None:
    override_db(fake_session_factory())

    response = client.get("/auth/me")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_auth_me_with_invalid_token_returns_401(
    client,
    override_db,
    fake_session_factory,
) -> None:
    override_db(fake_session_factory())

    response = client.get(
        "/auth/me",
        headers={"Authorization": "Bearer invalid-token"},
    )

    assert response.status_code == 401


def test_auth_me_with_expired_token_returns_401(
    client,
    override_db,
    fake_session_factory,
) -> None:
    settings = get_settings()
    assert settings.jwt_secret_key is not None
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "sub": "42",
            "iat": now - timedelta(minutes=31),
            "exp": now - timedelta(minutes=1),
            "type": "access",
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "ver": 0,
        },
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    override_db(fake_session_factory())

    response = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401


def test_auth_me_when_user_does_not_exist_returns_401(
    client,
    override_db,
    fake_session_factory,
    access_token,
) -> None:
    override_db(fake_session_factory(get_result=None))

    response = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    assert response.status_code == 401


def test_auth_me_rejects_inactive_user(
    client,
    override_db,
    fake_session_factory,
    user_factory,
    access_token,
) -> None:
    inactive_user = user_factory(is_active=False)
    override_db(fake_session_factory(get_result=inactive_user))

    response = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    assert response.status_code == 401


def test_auth_me_rejects_mismatched_token_version(
    client,
    override_db,
    fake_session_factory,
    user_factory,
) -> None:
    current_user = user_factory(token_version=3)
    old_token = create_access_token(current_user.id, 2)
    override_db(fake_session_factory(get_result=current_user))

    response = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {old_token}"},
    )

    assert response.status_code == 401


def test_auth_me_database_error_returns_503(
    client,
    override_db,
    fake_session_factory,
    access_token,
) -> None:
    session = fake_session_factory(
        get_error=SQLAlchemyError("private database detail")
    )
    override_db(session)

    response = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    assert response.status_code == 503
    assert session.rollback_called is True
    assert "private database detail" not in response.text


def test_health_endpoint_remains_available(client) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
