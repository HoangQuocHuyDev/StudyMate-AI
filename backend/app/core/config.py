"""Environment-based application configuration."""

import os
from dataclasses import dataclass, field
from functools import lru_cache
from math import isfinite
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
DEFAULT_JWT_ISSUER = "studymate-ai"
DEFAULT_JWT_AUDIENCE = "studymate-ai-api"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
MINIMUM_JWT_SECRET_LENGTH = 32
JWT_SECRET_PLACEHOLDER = "GENERATE_WITH_secrets_token_urlsafe_48"
DEFAULT_CORS_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
)
DEFAULT_STORAGE_ROOT = BACKEND_DIR / "storage" / "documents"
DEFAULT_MAX_UPLOAD_SIZE_BYTES = 10 * 1024 * 1024
DEFAULT_CHROMA_PERSIST_DIRECTORY = BACKEND_DIR / "storage" / "chroma"
DEFAULT_CHROMA_COLLECTION_NAME = (
    "studymate_document_chunks_gemini2_768_v1"
)
DEFAULT_GEMINI_EMBEDDING_MODEL = "gemini-embedding-2"
DEFAULT_GEMINI_EMBEDDING_DIMENSIONS = 768
DEFAULT_GEMINI_CHAT_MODEL = "gemini-3.5-flash-lite"
DEFAULT_GEMINI_CHAT_TIMEOUT_SECONDS = 30
DEFAULT_RAG_MAX_CONTEXT_CHARS = 12_000
DEFAULT_DOCUMENT_DELETION_LEASE_SECONDS = 60
DEFAULT_SUMMARY_GLOBAL_CONCURRENCY = 4
DEFAULT_SUMMARY_USER_CONCURRENCY = 1
DEFAULT_CHAT_GLOBAL_CONCURRENCY = 4
DEFAULT_CHAT_USER_CONCURRENCY = 1
DEFAULT_INDEXING_GLOBAL_CONCURRENCY = 2
DEFAULT_INDEXING_USER_CONCURRENCY = 1
DEFAULT_CHAT_DEADLINE_SECONDS = 60
DEFAULT_SUMMARY_DEADLINE_SECONDS = 120
MAX_GEMINI_CHAT_TIMEOUT_SECONDS = 300
MIN_RAG_MAX_CONTEXT_CHARS = 256
MAX_RAG_MAX_CONTEXT_CHARS = 200_000


@dataclass(frozen=True, slots=True)
class Settings:
    """Validated runtime settings loaded from environment variables."""

    database_url: str = field(repr=False)
    jwt_secret_key: str | None = field(repr=False)
    jwt_algorithm: str
    jwt_issuer: str
    jwt_audience: str
    access_token_expire_minutes: int
    cors_origins: tuple[str, ...]
    storage_root: Path
    max_upload_size_bytes: int
    chroma_persist_directory: Path
    chroma_collection_name: str
    gemini_api_key: str | None = field(repr=False)
    gemini_embedding_model: str
    gemini_embedding_dimensions: int
    gemini_chat_model: str
    gemini_chat_timeout_seconds: int
    rag_max_context_chars: int
    rag_max_cosine_distance: float | None = None
    summary_global_concurrency: int = DEFAULT_SUMMARY_GLOBAL_CONCURRENCY
    summary_user_concurrency: int = DEFAULT_SUMMARY_USER_CONCURRENCY
    chat_global_concurrency: int = DEFAULT_CHAT_GLOBAL_CONCURRENCY
    chat_user_concurrency: int = DEFAULT_CHAT_USER_CONCURRENCY
    indexing_global_concurrency: int = DEFAULT_INDEXING_GLOBAL_CONCURRENCY
    indexing_user_concurrency: int = DEFAULT_INDEXING_USER_CONCURRENCY
    chat_deadline_seconds: int = DEFAULT_CHAT_DEADLINE_SECONDS
    summary_deadline_seconds: int = DEFAULT_SUMMARY_DEADLINE_SECONDS
    document_deletion_lease_seconds: int = (
        DEFAULT_DOCUMENT_DELETION_LEASE_SECONDS
    )
    document_deletion_recovery_enabled: bool = False


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


def _load_jwt_claim_setting(environment_name: str, default: str) -> str:
    value = os.getenv(environment_name, default)
    if not value.strip() or value != value.strip():
        raise RuntimeError(f"{environment_name} must be a non-empty trimmed value.")
    return value


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


def _load_cors_origins() -> tuple[str, ...]:
    raw_value = os.getenv("CORS_ORIGINS")
    if raw_value is None:
        return DEFAULT_CORS_ORIGINS

    origins = tuple(
        dict.fromkeys(
            origin.strip()
            for origin in raw_value.split(",")
            if origin.strip()
        )
    )
    if not origins:
        raise RuntimeError("CORS_ORIGINS must contain at least one origin.")
    if "*" in origins:
        raise RuntimeError("CORS_ORIGINS must not contain a wildcard origin.")

    return origins


def _load_storage_root() -> Path:
    raw_value = os.getenv("STORAGE_ROOT")
    if raw_value is not None and not raw_value.strip():
        raise RuntimeError("STORAGE_ROOT must not be empty.")

    configured_path = Path(raw_value) if raw_value else DEFAULT_STORAGE_ROOT
    if not configured_path.is_absolute():
        configured_path = BACKEND_DIR / configured_path
    return configured_path.expanduser().resolve(strict=False)


def _load_max_upload_size_bytes() -> int:
    raw_value = os.getenv(
        "MAX_UPLOAD_SIZE_BYTES",
        str(DEFAULT_MAX_UPLOAD_SIZE_BYTES),
    )
    try:
        max_upload_size_bytes = int(raw_value)
    except ValueError as exc:
        raise RuntimeError("MAX_UPLOAD_SIZE_BYTES must be an integer.") from exc
    if max_upload_size_bytes <= 0:
        raise RuntimeError("MAX_UPLOAD_SIZE_BYTES must be greater than zero.")
    return max_upload_size_bytes


def _load_chroma_persist_directory() -> Path:
    raw_value = os.getenv("CHROMA_PERSIST_DIRECTORY")
    if raw_value is not None and not raw_value.strip():
        raise RuntimeError("CHROMA_PERSIST_DIRECTORY must not be empty.")

    configured_path = (
        Path(raw_value)
        if raw_value
        else DEFAULT_CHROMA_PERSIST_DIRECTORY
    )
    if not configured_path.is_absolute():
        configured_path = BACKEND_DIR / configured_path
    return configured_path.expanduser().resolve(strict=False)


def _load_chroma_collection_name() -> str:
    raw_value = os.getenv(
        "CHROMA_COLLECTION_NAME",
        DEFAULT_CHROMA_COLLECTION_NAME,
    )
    collection_name = raw_value.strip()
    if not collection_name:
        raise RuntimeError("CHROMA_COLLECTION_NAME must not be empty.")
    return collection_name


def _load_gemini_api_key() -> str | None:
    raw_value = os.getenv("GEMINI_API_KEY")
    if raw_value is None:
        return None
    if not raw_value.strip() or raw_value != raw_value.strip():
        raise RuntimeError("GEMINI_API_KEY is invalid.")
    return raw_value


def _load_gemini_embedding_model() -> str:
    raw_value = os.getenv(
        "GEMINI_EMBEDDING_MODEL",
        DEFAULT_GEMINI_EMBEDDING_MODEL,
    )
    model_name = raw_value.strip()
    if not model_name:
        raise RuntimeError("GEMINI_EMBEDDING_MODEL must not be empty.")
    return model_name


def _load_gemini_embedding_dimensions() -> int:
    raw_value = os.getenv(
        "GEMINI_EMBEDDING_DIMENSIONS",
        str(DEFAULT_GEMINI_EMBEDDING_DIMENSIONS),
    )
    try:
        dimensions = int(raw_value)
    except ValueError as exc:
        raise RuntimeError(
            "GEMINI_EMBEDDING_DIMENSIONS must be an integer."
        ) from exc
    if dimensions <= 0:
        raise RuntimeError(
            "GEMINI_EMBEDDING_DIMENSIONS must be greater than zero."
        )
    return dimensions


def _load_gemini_chat_model() -> str:
    raw_value = os.getenv(
        "GEMINI_CHAT_MODEL",
        DEFAULT_GEMINI_CHAT_MODEL,
    )
    model_name = raw_value.strip()
    if not model_name:
        raise RuntimeError("GEMINI_CHAT_MODEL must not be empty.")
    return model_name


def _load_gemini_chat_timeout_seconds() -> int:
    raw_value = os.getenv(
        "GEMINI_CHAT_TIMEOUT_SECONDS",
        str(DEFAULT_GEMINI_CHAT_TIMEOUT_SECONDS),
    )
    try:
        timeout_seconds = int(raw_value)
    except ValueError as exc:
        raise RuntimeError(
            "GEMINI_CHAT_TIMEOUT_SECONDS must be an integer."
        ) from exc
    if timeout_seconds < 1 or timeout_seconds > MAX_GEMINI_CHAT_TIMEOUT_SECONDS:
        raise RuntimeError(
            "GEMINI_CHAT_TIMEOUT_SECONDS must be between 1 and "
            f"{MAX_GEMINI_CHAT_TIMEOUT_SECONDS}."
        )
    return timeout_seconds


def _load_rag_max_context_chars() -> int:
    raw_value = os.getenv(
        "RAG_MAX_CONTEXT_CHARS",
        str(DEFAULT_RAG_MAX_CONTEXT_CHARS),
    )
    try:
        max_context_chars = int(raw_value)
    except ValueError as exc:
        raise RuntimeError(
            "RAG_MAX_CONTEXT_CHARS must be an integer."
        ) from exc
    if (
        max_context_chars < MIN_RAG_MAX_CONTEXT_CHARS
        or max_context_chars > MAX_RAG_MAX_CONTEXT_CHARS
    ):
        raise RuntimeError(
            f"RAG_MAX_CONTEXT_CHARS must be between "
            f"{MIN_RAG_MAX_CONTEXT_CHARS} and {MAX_RAG_MAX_CONTEXT_CHARS}."
        )
    return max_context_chars


def _load_rag_max_cosine_distance() -> float | None:
    """Load an optional cosine-distance cutoff; lower means more relevant."""

    raw_value = os.getenv("RAG_MAX_COSINE_DISTANCE")
    if raw_value is None or raw_value.strip().lower() in {
        "off",
        "none",
        "disabled",
    }:
        return None
    if not raw_value.strip():
        raise RuntimeError(
            "RAG_MAX_COSINE_DISTANCE must be a number from 0 to 2 or 'off'."
        )
    try:
        max_distance = float(raw_value)
    except ValueError as exc:
        raise RuntimeError(
            "RAG_MAX_COSINE_DISTANCE must be a number from 0 to 2 or 'off'."
        ) from exc
    if not isfinite(max_distance) or max_distance < 0 or max_distance > 2:
        raise RuntimeError(
            "RAG_MAX_COSINE_DISTANCE must be between 0 and 2."
        )
    return max_distance


def _load_concurrency_limit(environment_name: str, default: int) -> int:
    raw_value = os.getenv(environment_name, str(default))
    try:
        limit = int(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{environment_name} must be an integer.") from exc
    if limit < 1 or limit > 64:
        raise RuntimeError(f"{environment_name} must be between 1 and 64.")
    return limit


def _load_summary_deadline_seconds() -> int:
    raw_value = os.getenv(
        "SUMMARY_DEADLINE_SECONDS",
        str(DEFAULT_SUMMARY_DEADLINE_SECONDS),
    )
    try:
        deadline_seconds = int(raw_value)
    except ValueError as exc:
        raise RuntimeError("SUMMARY_DEADLINE_SECONDS must be an integer.") from exc
    if deadline_seconds < 5 or deadline_seconds > 1_800:
        raise RuntimeError(
            "SUMMARY_DEADLINE_SECONDS must be between 5 and 1800."
        )
    return deadline_seconds


def _load_chat_deadline_seconds() -> int:
    raw_value = os.getenv(
        "CHAT_DEADLINE_SECONDS",
        str(DEFAULT_CHAT_DEADLINE_SECONDS),
    )
    try:
        deadline_seconds = int(raw_value)
    except ValueError as exc:
        raise RuntimeError("CHAT_DEADLINE_SECONDS must be an integer.") from exc
    if deadline_seconds < 5 or deadline_seconds > 600:
        raise RuntimeError(
            "CHAT_DEADLINE_SECONDS must be between 5 and 600."
        )
    return deadline_seconds


def _load_document_deletion_lease_seconds() -> int:
    raw_value = os.getenv(
        "DOCUMENT_DELETION_LEASE_SECONDS",
        str(DEFAULT_DOCUMENT_DELETION_LEASE_SECONDS),
    )
    try:
        lease_seconds = int(raw_value)
    except ValueError as exc:
        raise RuntimeError(
            "DOCUMENT_DELETION_LEASE_SECONDS must be an integer."
        ) from exc
    if lease_seconds < 1 or lease_seconds > 3_600:
        raise RuntimeError(
            "DOCUMENT_DELETION_LEASE_SECONDS must be between 1 and 3600."
        )
    return lease_seconds


def _load_document_deletion_recovery_enabled() -> bool:
    raw_value = os.getenv("DOCUMENT_DELETION_RECOVERY_ENABLED", "false")
    normalized = raw_value.strip().lower()
    if normalized not in {"true", "false"}:
        raise RuntimeError(
            "DOCUMENT_DELETION_RECOVERY_ENABLED must be true or false."
        )
    return normalized == "true"


@lru_cache
def get_settings() -> Settings:
    """Return the validated application settings without exposing secrets."""

    summary_global_concurrency = _load_concurrency_limit(
        "SUMMARY_GLOBAL_CONCURRENCY",
        DEFAULT_SUMMARY_GLOBAL_CONCURRENCY,
    )
    summary_user_concurrency = _load_concurrency_limit(
        "SUMMARY_USER_CONCURRENCY",
        DEFAULT_SUMMARY_USER_CONCURRENCY,
    )
    if summary_user_concurrency > summary_global_concurrency:
        raise RuntimeError(
            "SUMMARY_USER_CONCURRENCY must not exceed "
            "SUMMARY_GLOBAL_CONCURRENCY."
        )
    chat_global_concurrency = _load_concurrency_limit(
        "CHAT_GLOBAL_CONCURRENCY",
        DEFAULT_CHAT_GLOBAL_CONCURRENCY,
    )
    chat_user_concurrency = _load_concurrency_limit(
        "CHAT_USER_CONCURRENCY",
        DEFAULT_CHAT_USER_CONCURRENCY,
    )
    if chat_user_concurrency > chat_global_concurrency:
        raise RuntimeError(
            "CHAT_USER_CONCURRENCY must not exceed CHAT_GLOBAL_CONCURRENCY."
        )
    indexing_global_concurrency = _load_concurrency_limit(
        "INDEXING_GLOBAL_CONCURRENCY",
        DEFAULT_INDEXING_GLOBAL_CONCURRENCY,
    )
    indexing_user_concurrency = _load_concurrency_limit(
        "INDEXING_USER_CONCURRENCY",
        DEFAULT_INDEXING_USER_CONCURRENCY,
    )
    if indexing_user_concurrency > indexing_global_concurrency:
        raise RuntimeError(
            "INDEXING_USER_CONCURRENCY must not exceed "
            "INDEXING_GLOBAL_CONCURRENCY."
        )

    return Settings(
        database_url=_load_database_url(),
        jwt_secret_key=_load_jwt_secret_key(),
        jwt_algorithm=_load_jwt_algorithm(),
        jwt_issuer=_load_jwt_claim_setting("JWT_ISSUER", DEFAULT_JWT_ISSUER),
        jwt_audience=_load_jwt_claim_setting(
            "JWT_AUDIENCE",
            DEFAULT_JWT_AUDIENCE,
        ),
        access_token_expire_minutes=_load_access_token_expire_minutes(),
        cors_origins=_load_cors_origins(),
        storage_root=_load_storage_root(),
        max_upload_size_bytes=_load_max_upload_size_bytes(),
        chroma_persist_directory=_load_chroma_persist_directory(),
        chroma_collection_name=_load_chroma_collection_name(),
        gemini_api_key=_load_gemini_api_key(),
        gemini_embedding_model=_load_gemini_embedding_model(),
        gemini_embedding_dimensions=_load_gemini_embedding_dimensions(),
        gemini_chat_model=_load_gemini_chat_model(),
        gemini_chat_timeout_seconds=_load_gemini_chat_timeout_seconds(),
        rag_max_context_chars=_load_rag_max_context_chars(),
        rag_max_cosine_distance=_load_rag_max_cosine_distance(),
        summary_global_concurrency=summary_global_concurrency,
        summary_user_concurrency=summary_user_concurrency,
        chat_global_concurrency=chat_global_concurrency,
        chat_user_concurrency=chat_user_concurrency,
        indexing_global_concurrency=indexing_global_concurrency,
        indexing_user_concurrency=indexing_user_concurrency,
        chat_deadline_seconds=_load_chat_deadline_seconds(),
        summary_deadline_seconds=_load_summary_deadline_seconds(),
        document_deletion_lease_seconds=(
            _load_document_deletion_lease_seconds()
        ),
        document_deletion_recovery_enabled=(
            _load_document_deletion_recovery_enabled()
        ),
    )
