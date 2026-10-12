"""Reusable password hashing helpers."""

from datetime import datetime, timedelta, timezone

import jwt
from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError
from pwdlib.hashers.argon2 import Argon2Hasher

from app.core.config import Settings, get_settings


_password_hash = PasswordHash((Argon2Hasher(),))


class AccessTokenError(ValueError):
    """Raised when an access token is invalid or cannot be trusted."""


class JWTConfigurationError(RuntimeError):
    """Raised when JWT signing is not configured securely."""


def hash_password(password: str) -> str:
    """Return an Argon2id hash suitable for persistent storage."""

    return _password_hash.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Return whether a plain password matches a stored Argon2 hash."""

    try:
        return _password_hash.verify(plain_password, hashed_password)
    except UnknownHashError:
        return False


def _get_jwt_settings() -> Settings:
    settings = get_settings()
    if settings.jwt_secret_key is None:
        raise JWTConfigurationError(
            "JWT_SECRET_KEY is not configured in the environment."
        )
    return settings


def create_access_token(user_id: int) -> str:
    """Create a signed access token for a positive user identifier."""

    if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
        raise ValueError("user_id must be a positive integer.")

    settings = _get_jwt_settings()
    issued_at = datetime.now(timezone.utc)
    expires_at = issued_at + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    payload = {
        "sub": str(user_id),
        "iat": issued_at,
        "exp": expires_at,
        "type": "access",
    }

    return jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def decode_access_token(token: str) -> int:
    """Validate an access token and return its positive user identifier."""

    settings = _get_jwt_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            options={
                "require": ["sub", "exp", "iat", "type"],
                "verify_signature": True,
                "verify_exp": True,
                "verify_iat": True,
            },
        )
    except jwt.InvalidTokenError:
        raise AccessTokenError("Access token is invalid or expired.") from None

    if payload.get("type") != "access":
        raise AccessTokenError("Access token is invalid or expired.")

    subject = payload.get("sub")
    if (
        not isinstance(subject, str)
        or not subject.isascii()
        or not subject.isdecimal()
    ):
        raise AccessTokenError("Access token is invalid or expired.")

    user_id = int(subject)
    if user_id <= 0 or str(user_id) != subject:
        raise AccessTokenError("Access token is invalid or expired.")

    return user_id
