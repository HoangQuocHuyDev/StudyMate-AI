"""Tests for POST /auth/register."""

import pytest

from app.core.security import verify_password


VALID_REGISTRATION = {
    "full_name": "Register User",
    "username": "register_user",
    "password": "Register123",
    "confirm_password": "Register123",
}


def test_register_success_hashes_password_and_hides_hash(
    client,
    override_db,
    fake_session_factory,
) -> None:
    session = fake_session_factory(scalar_result=None)
    override_db(session)

    response = client.post("/auth/register", json=VALID_REGISTRATION)

    assert response.status_code == 201
    assert session.committed is True
    assert session.added is not None
    assert session.added.role == "USER"
    assert session.added.password_hash.startswith("$argon2id$")
    assert verify_password(
        VALID_REGISTRATION["password"],
        session.added.password_hash,
    )
    assert "password_hash" not in response.json()


def test_register_duplicate_username_returns_409(
    client,
    override_db,
    fake_session_factory,
) -> None:
    override_db(fake_session_factory(scalar_result=1))

    response = client.post("/auth/register", json=VALID_REGISTRATION)

    assert response.status_code == 409


@pytest.mark.parametrize(
    "changes",
    [
        {"username": "invalid-name"},
        {"username": "ab"},
        {"password": "short1", "confirm_password": "short1"},
        {"password": "OnlyLetters", "confirm_password": "OnlyLetters"},
        {"password": "12345678", "confirm_password": "12345678"},
    ],
)
def test_register_rejects_invalid_username_or_password(
    client,
    override_db,
    fake_session_factory,
    changes,
) -> None:
    override_db(fake_session_factory())

    response = client.post(
        "/auth/register",
        json={**VALID_REGISTRATION, **changes},
    )

    assert response.status_code == 422


def test_register_rejects_mismatched_confirmation(
    client,
    override_db,
    fake_session_factory,
) -> None:
    override_db(fake_session_factory())

    response = client.post(
        "/auth/register",
        json={**VALID_REGISTRATION, "confirm_password": "Different123"},
    )

    assert response.status_code == 422


def test_public_registration_cannot_assign_admin(
    client,
    override_db,
    fake_session_factory,
) -> None:
    session = fake_session_factory()
    override_db(session)

    response = client.post(
        "/auth/register",
        json={**VALID_REGISTRATION, "role": "ADMIN"},
    )

    assert response.status_code == 422
    assert session.added is None
