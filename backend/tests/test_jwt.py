"""Unit tests for JWT access-token utilities."""

import secrets
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.core.config import get_settings
from app.core.security import AccessTokenError, create_access_token, decode_access_token


def _base_payload() -> dict[str, object]:
    now = datetime.now(timezone.utc)
    settings = get_settings()
    return {
        "sub": "42",
        "iat": now,
        "exp": now + timedelta(minutes=30),
        "type": "access",
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "ver": 0,
    }


def _encode(payload: dict[str, object], *, algorithm: str = "HS256") -> str:
    settings = get_settings()
    assert settings.jwt_secret_key is not None
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=algorithm)


def test_create_and_decode_access_token() -> None:
    token = create_access_token(42, 7)

    claims = decode_access_token(token)
    assert claims.user_id == 42
    assert claims.token_version == 7
    settings = get_settings()
    payload = jwt.decode(
        token,
        settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
    )
    assert payload["iss"] == "studymate-ai"
    assert payload["aud"] == "studymate-ai-api"
    assert payload["ver"] == 7


def test_expired_token_is_rejected() -> None:
    now = datetime.now(timezone.utc)
    token = _encode(
        {
            "sub": "42",
            "iat": now - timedelta(minutes=31),
            "exp": now - timedelta(minutes=1),
            "type": "access",
            "ver": 0,
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


@pytest.mark.parametrize(
    "missing_claim",
    ["sub", "iat", "exp", "type", "iss", "aud", "ver"],
)
def test_missing_required_claim_is_rejected(missing_claim: str) -> None:
    payload = _base_payload()
    payload.pop(missing_claim)

    with pytest.raises(AccessTokenError):
        decode_access_token(_encode(payload))


@pytest.mark.parametrize(
    "claim,wrong_value",
    [
        ("iss", "another-issuer"),
        ("aud", "another-audience"),
    ],
)
def test_wrong_issuer_or_audience_is_rejected(
    claim: str,
    wrong_value: str,
) -> None:
    token = _encode({**_base_payload(), claim: wrong_value})

    with pytest.raises(AccessTokenError):
        decode_access_token(token)


def test_multiple_audiences_are_rejected_even_when_one_matches() -> None:
    settings = get_settings()
    token = _encode(
        {
            **_base_payload(),
            "aud": [settings.jwt_audience, "another-audience"],
        }
    )

    with pytest.raises(AccessTokenError):
        decode_access_token(token)


@pytest.mark.parametrize("subject", ["invalid", "0", "-1", "01", 42])
def test_invalid_subject_is_rejected(subject: object) -> None:
    token = _encode({**_base_payload(), "sub": subject})

    with pytest.raises(AccessTokenError):
        decode_access_token(token)


def test_disallowed_algorithm_is_rejected() -> None:
    token = _encode(_base_payload(), algorithm="HS384")

    with pytest.raises(AccessTokenError):
        decode_access_token(token)


@pytest.mark.parametrize("token_version", [True, "0", 0.0, -1, None])
def test_invalid_token_version_is_rejected(token_version: object) -> None:
    token = _encode({**_base_payload(), "ver": token_version})

    with pytest.raises(AccessTokenError):
        decode_access_token(token)


@pytest.mark.parametrize("token_version", [True, "0", 0.0, -1])
def test_invalid_token_version_cannot_be_issued(token_version: object) -> None:
    with pytest.raises(ValueError):
        create_access_token(42, token_version)  # type: ignore[arg-type]
