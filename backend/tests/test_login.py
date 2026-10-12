"""Tests for POST /auth/login."""


def test_login_success_returns_bearer_token(
    client,
    override_db,
    fake_session_factory,
    active_user,
    plain_password,
) -> None:
    override_db(fake_session_factory(scalar_result=active_user))

    response = client.post(
        "/auth/login",
        json={"username": active_user.username, "password": plain_password},
    )

    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"
    assert response.json()["access_token"]
    assert "password_hash" not in response.json()


def test_unknown_username_and_wrong_password_share_generic_401(
    client,
    override_db,
    fake_session_factory,
    active_user,
) -> None:
    override_db(fake_session_factory(scalar_result=None))
    unknown_response = client.post(
        "/auth/login",
        json={"username": "missing_user", "password": "AnyPassword1"},
    )

    override_db(fake_session_factory(scalar_result=active_user))
    wrong_response = client.post(
        "/auth/login",
        json={"username": active_user.username, "password": "WrongPassword1"},
    )

    assert unknown_response.status_code == 401
    assert wrong_response.status_code == 401
    assert unknown_response.json() == wrong_response.json()


def test_inactive_account_cannot_login(
    client,
    override_db,
    fake_session_factory,
    user_factory,
    plain_password,
) -> None:
    inactive_user = user_factory(is_active=False)
    override_db(fake_session_factory(scalar_result=inactive_user))

    response = client.post(
        "/auth/login",
        json={"username": inactive_user.username, "password": plain_password},
    )

    assert response.status_code == 401
    assert "password_hash" not in response.json()
