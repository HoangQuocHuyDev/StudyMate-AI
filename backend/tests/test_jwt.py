"""Unit tests for JWT access-token utilities."""

import secrets
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.core.config import get_settings
from app.core.security import AccessTokenError, create_access_token, decode_access_token


def _base_payload() -> dict[str, object]:
    now = datetime.now(timezone.utc)
    return {
        "sub": "42",
        "iat": now,
        "exp": now + timedelta(minutes=30),
        "type": "access",
    }


def _encode(payload: dict[str, object], *, algorithm: str = "HS256") -> str:
    settings = get_settings()
    assert settings.jwt_secret_key is not None
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=algorithm)


def test_create_and_decode_access_token() -> None:
    token = create_access_token(42)

    assert decode_access_token(token) == 42


def test_expired_token_is_rejected() -> None:
    now = datetime.now(timezone.utc)
    token = _encode(
        {
            "sub": "42",
            "iat": now - timedelta(minutes=31),
            "exp": now - timedelta(minutes=1),
            "type": "access",
        }
    )

    with pytest.raises(AccessTokenError):
        decode_access_token(token)


def test_wrong_signature_is_rejected() -> None:
    token = jwt.encode(
        _base_payload(),
        secrets.token_urlsafe(48),
        algorithm="HS256",
    )

    with pytest.raises(AccessTokenError):
        decode_access_token(token)


def test_wrong_token_type_is_rejected() -> None:
    token = _encode({**_base_payload(), "type": "refresh"})

    with pytest.raises(AccessTokenError):
        decode_access_token(token)


@pytest.mark.parametrize("missing_claim", ["sub", "iat", "exp", "type"])
def test_missing_required_claim_is_rejected(missing_claim: str) -> None:
    payload = _base_payload()
    payload.pop(missing_claim)

    with pytest.raises(AccessTokenError):
        decode_access_token(_encode(payload))


@pytest.mark.parametrize("subject", ["invalid", "0", "-1", "01", 42])
def test_invalid_subject_is_rejected(subject: object) -> None:
    token = _encode({**_base_payload(), "sub": subject})

    with pytest.raises(AccessTokenError):
        decode_access_token(token)


def test_disallowed_algorithm_is_rejected() -> None:
    token = _encode(_base_payload(), algorithm="HS384")

    with pytest.raises(AccessTokenError):
        decode_access_token(token)
