"""Security tests for login and registration request rate limiting."""

from __future__ import annotations

import logging

import pytest

from app.main import app
from app.services.auth_rate_limiter import (
    AuthenticationRateLimiter,
    AuthenticationRateLimitExceeded,
    LOGIN_IP_LIMIT,
    LOGIN_IP_USERNAME_LIMIT,
    LOGIN_WINDOW_SECONDS,
    REGISTER_IP_LIMIT,
    REGISTER_WINDOW_SECONDS,
    get_authentication_rate_limiter,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def limiter(clock: FakeClock) -> AuthenticationRateLimiter:
    return AuthenticationRateLimiter(
        clock=clock,
        key_secret=b"test-only-rate-limit-key-32-bytes",
    )


@pytest.fixture
def limited_client(client, limiter: AuthenticationRateLimiter):
    app.dependency_overrides[get_authentication_rate_limiter] = lambda: limiter
    yield client
    app.dependency_overrides.pop(get_authentication_rate_limiter, None)


def _login(client, username: str, *, forwarded_for: str | None = None):
    headers = {"X-Forwarded-For": forwarded_for} if forwarded_for else None
    return client.post(
        "/auth/login",
        json={"username": username, "password": "WrongPassword1"},
        headers=headers,
    )


def test_login_pair_limit_returns_429_with_retry_after(
    limited_client,
    override_db,
    fake_session_factory,
) -> None:
    override_db(fake_session_factory(scalar_result=None))

    for _ in range(LOGIN_IP_USERNAME_LIMIT):
        assert _login(limited_client, "missing_user").status_code == 401

    response = _login(limited_client, "missing_user")

    assert response.status_code == 429
    assert response.headers["Retry-After"] == str(LOGIN_WINDOW_SECONDS)
    assert response.json() == {
        "detail": "Quá nhiều yêu cầu xác thực. Vui lòng thử lại sau."
    }


def test_login_window_expiry_allows_another_attempt(
    limited_client,
    clock: FakeClock,
    override_db,
    fake_session_factory,
) -> None:
    override_db(fake_session_factory(scalar_result=None))
    for _ in range(LOGIN_IP_USERNAME_LIMIT):
        _login(limited_client, "missing_user")
    assert _login(limited_client, "missing_user").status_code == 429

    clock.advance(LOGIN_WINDOW_SECONDS)

    assert _login(limited_client, "missing_user").status_code == 401


def test_forged_forwarded_for_does_not_bypass_login_limit(
    limited_client,
    override_db,
    fake_session_factory,
) -> None:
    override_db(fake_session_factory(scalar_result=None))
    for index in range(LOGIN_IP_USERNAME_LIMIT):
        response = _login(
            limited_client,
            "missing_user",
            forwarded_for=f"198.51.100.{index + 1}",
        )
        assert response.status_code == 401

    response = _login(
        limited_client,
        "missing_user",
        forwarded_for="203.0.113.99",
    )

    assert response.status_code == 429


def test_login_ip_limit_is_shared_across_distinct_usernames(
    limiter: AuthenticationRateLimiter,
) -> None:
    for index in range(LOGIN_IP_LIMIT):
        limiter.check_login(
            client_host="192.0.2.10",
            username=f"student_{index}",
        )

    with pytest.raises(AuthenticationRateLimitExceeded):
        limiter.check_login(
            client_host="192.0.2.10",
            username="another_student",
        )

    limiter.check_login(
        client_host="192.0.2.11",
        username="another_student",
    )


def test_register_is_rate_limited_per_ip(
    limited_client,
    override_db,
    fake_session_factory,
) -> None:
    override_db(fake_session_factory(scalar_result=1))
    payload = {
        "full_name": "Register User",
        "username": "register_user",
        "password": "Register123",
        "confirm_password": "Register123",
    }
    for _ in range(REGISTER_IP_LIMIT):
        assert limited_client.post("/auth/register", json=payload).status_code == 409

    response = limited_client.post("/auth/register", json=payload)

    assert response.status_code == 429
    assert response.headers["Retry-After"] == str(REGISTER_WINDOW_SECONDS)


def test_register_window_expiry_allows_another_attempt(
    limiter: AuthenticationRateLimiter,
    clock: FakeClock,
) -> None:
    for _ in range(REGISTER_IP_LIMIT):
        limiter.check_register(client_host="192.0.2.20")
    with pytest.raises(AuthenticationRateLimitExceeded):
        limiter.check_register(client_host="192.0.2.20")

    clock.advance(REGISTER_WINDOW_SECONDS)

    limiter.check_register(client_host="192.0.2.20")


def test_rate_limiter_does_not_log_credentials_or_raw_keys(
    limiter: AuthenticationRateLimiter,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    limiter.check_login(
        client_host="192.0.2.30",
        username="sensitive_student",
    )

    output = caplog.text
    assert "sensitive_student" not in output
    assert "WrongPassword1" not in output
    assert "192.0.2.30" not in output


def test_limiter_evicts_oldest_key_when_capacity_is_reached(
    clock: FakeClock,
) -> None:
    small_limiter = AuthenticationRateLimiter(
        clock=clock,
        key_secret=b"test-only-rate-limit-key-32-bytes",
        max_tracked_keys=3,
    )
    small_limiter.check_register(client_host="192.0.2.1")
    clock.advance(1)
    small_limiter.check_register(client_host="192.0.2.2")
    clock.advance(1)
    small_limiter.check_register(client_host="192.0.2.3")
    clock.advance(1)

    small_limiter.check_register(client_host="192.0.2.4")

    assert len(small_limiter._events) == 3
