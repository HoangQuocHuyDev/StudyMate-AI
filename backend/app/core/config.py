"""Environment-based application configuration."""

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


BACKEND_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BACKEND_DIR / ".env")

EXPECTED_DATABASE = "studymate_ai_db"
EXPECTED_DRIVER = "postgresql+psycopg"
EXPECTED_HOST = "127.0.0.1"
EXPECTED_PORT = 5432
EXPECTED_USER = "postgres"
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
MINIMUM_JWT_SECRET_LENGTH = 32
JWT_SECRET_PLACEHOLDER = "GENERATE_WITH_secrets_token_urlsafe_48"


@dataclass(frozen=True, slots=True)
class Settings:
    """Validated runtime settings loaded from environment variables."""

    database_url: str = field(repr=False)
    jwt_secret_key: str | None = field(repr=False)
    jwt_algorithm: str
    access_token_expire_minutes: int


def _load_database_url() -> str:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL is not configured. Create backend/.env from .env.example."
        )

    try:
        url = make_url(database_url)
    except ArgumentError as exc:
        raise RuntimeError("DATABASE_URL is not a valid SQLAlchemy URL.") from exc

    expected_target = (
        url.drivername == EXPECTED_DRIVER
        and url.host == EXPECTED_HOST
        and url.port == EXPECTED_PORT
        and url.username == EXPECTED_USER
        and url.database == EXPECTED_DATABASE
    )
    if not expected_target:
        raise RuntimeError(
            "DATABASE_URL must target PostgreSQL database studymate_ai_db "
            "at 127.0.0.1:5432 with user postgres."
        )

    return database_url


def _load_jwt_secret_key() -> str | None:
    jwt_secret_key = os.getenv("JWT_SECRET_KEY")
    if not jwt_secret_key:
        return None
    if (
        jwt_secret_key == JWT_SECRET_PLACEHOLDER
        or len(jwt_secret_key) < MINIMUM_JWT_SECRET_LENGTH
    ):
        raise RuntimeError(
            "JWT_SECRET_KEY must be a generated secret of at least 32 characters."
        )
    return jwt_secret_key


def _load_jwt_algorithm() -> str:
    jwt_algorithm = os.getenv("JWT_ALGORITHM", JWT_ALGORITHM)
    if jwt_algorithm != JWT_ALGORITHM:
        raise RuntimeError("JWT_ALGORITHM must be HS256.")
    return jwt_algorithm


def _load_access_token_expire_minutes() -> int:
    raw_value = os.getenv(
        "ACCESS_TOKEN_EXPIRE_MINUTES",
        str(ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    try:
        expire_minutes = int(raw_value)
    except ValueError as exc:
        raise RuntimeError(
            "ACCESS_TOKEN_EXPIRE_MINUTES must be an integer."
        ) from exc
    if expire_minutes <= 0:
        raise RuntimeError(
            "ACCESS_TOKEN_EXPIRE_MINUTES must be greater than zero."
        )
    return expire_minutes


@lru_cache
def get_settings() -> Settings:
    """Return the validated application settings without exposing secrets."""

    return Settings(
        database_url=_load_database_url(),
        jwt_secret_key=_load_jwt_secret_key(),
        jwt_algorithm=_load_jwt_algorithm(),
        access_token_expire_minutes=_load_access_token_expire_minutes(),
    )
