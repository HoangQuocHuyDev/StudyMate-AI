"""Gemini text embeddings with validated, provider-neutral output."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from math import isfinite
from numbers import Real
from time import perf_counter
from typing import Any, Protocol

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from app.core.config import Settings


DEFAULT_REQUEST_TIMEOUT_MILLISECONDS = 30_000
DOCUMENT_TEMPLATE = "title: none | text: {text}"
QUERY_TEMPLATE = "task: question answering | query: {query}"
_SAFE_PROVIDER_HTTP_STATUSES = frozenset(
    {400, 401, 403, 404, 408, 413, 422, 429, 500, 502, 503, 504}
)


class EmbeddingProvider(Protocol):
    """Small interface used by indexing and retrieval services."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed document chunks while preserving input order."""

    def embed_query(
        self,
        query: str,
        *,
        timeout_seconds: float | None = None,
    ) -> list[float]:
        """Embed one user retrieval query."""


class GeminiEmbeddingError(Exception):
    """Base error carrying only diagnostic-safe Gemini failure metadata."""

    default_error_code = "gemini_request_failed"
    default_failure_phase = "sdk_call"
    default_exception_type: str | None = None

    def __init__(
        self,
        message: str,
        *,
        error_code: str | None = None,
        failure_phase: str | None = None,
        provider_http_status: int | None = None,
        exception_type: str | None = None,
        elapsed_ms: float | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code or self.default_error_code
        self.failure_phase = failure_phase or self.default_failure_phase
        self.provider_http_status = provider_http_status
        self.exception_type = (
            exception_type
            if exception_type is not None
            else self.default_exception_type
        )
        self.elapsed_ms = elapsed_ms


class GeminiEmbeddingConfigurationError(GeminiEmbeddingError):
    """Raised when Gemini embedding configuration is incomplete."""

    default_error_code = "gemini_client_creation_failed"
    default_failure_phase = "client_creation"
    default_exception_type = "GeminiEmbeddingConfigurationError"


class InvalidEmbeddingInputError(GeminiEmbeddingError, ValueError):
    """Raised before a request when text input is invalid."""

    default_error_code = "gemini_input_validation_failed"
    default_failure_phase = "input_validation"
    default_exception_type = "InvalidEmbeddingInputError"


class GeminiEmbeddingRequestError(GeminiEmbeddingError):
    """Raised when the SDK cannot complete an embedding request."""


class InvalidEmbeddingResponseError(GeminiEmbeddingError):
    """Raised when Gemini returns missing or malformed vectors."""

    default_error_code = "gemini_invalid_response"
    default_failure_phase = "response_validation"
    default_exception_type = "InvalidEmbeddingResponseError"


class GeminiEmbeddingService:
    """Generate fixed-size text embeddings through the official Gemini SDK."""

    def __init__(
        self,
        settings: Settings,
        *,
        client: Any | None = None,
        client_factory: Callable[..., Any] | None = None,
        timeout_milliseconds: int = DEFAULT_REQUEST_TIMEOUT_MILLISECONDS,
    ) -> None:
        started = perf_counter()
        if (
            isinstance(settings.gemini_embedding_dimensions, bool)
            or settings.gemini_embedding_dimensions <= 0
        ):
            raise GeminiEmbeddingConfigurationError(
                "Embedding dimensions must be positive.",
                elapsed_ms=_elapsed_ms(started),
            )
        if not settings.gemini_embedding_model.strip():
            raise GeminiEmbeddingConfigurationError(
                "Gemini embedding model is not configured.",
                elapsed_ms=_elapsed_ms(started),
            )
        if (
            isinstance(timeout_milliseconds, bool)
            or not isinstance(timeout_milliseconds, int)
            or timeout_milliseconds <= 0
        ):
            raise GeminiEmbeddingConfigurationError(
                "Gemini request timeout must be positive.",
                elapsed_ms=_elapsed_ms(started),
            )

        self._api_key = settings.gemini_api_key
        self._model = settings.gemini_embedding_model
        self._dimensions = settings.gemini_embedding_dimensions
        self._timeout_milliseconds = timeout_milliseconds
        self._client = client
        self._client_factory = (
            client_factory if client_factory is not None else genai.Client
        )
        self._owns_client = client is None

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed document chunks as one ordered SDK batch."""

        started = perf_counter()
        if not isinstance(texts, list) or not texts:
            raise InvalidEmbeddingInputError(
                "At least one document text is required.",
                elapsed_ms=_elapsed_ms(started),
            )
        formatted_texts: list[str] = []
        for text in texts:
            if not isinstance(text, str) or not text.strip():
                raise InvalidEmbeddingInputError(
                    "Document text must not be empty.",
                    elapsed_ms=_elapsed_ms(started),
                )
            formatted_texts.append(DOCUMENT_TEMPLATE.format(text=text))
        return self._embed(formatted_texts)

    def embed_query(
        self,
        query: str,
        *,
        timeout_seconds: float | None = None,
    ) -> list[float]:
        """Embed one question using the same model and dimensions."""

        started = perf_counter()
        if not isinstance(query, str) or not query.strip():
            raise InvalidEmbeddingInputError(
                "Query must not be empty.",
                elapsed_ms=_elapsed_ms(started),
            )
        vectors = self._embed(
            [QUERY_TEMPLATE.format(query=query)],
            timeout_seconds=timeout_seconds,
        )
        return vectors[0]

    def close(self) -> None:
        """Close a lazily created SDK client without owning injected clients."""

        if self._owns_client and self._client is not None:
            close = getattr(self._client, "close", None)
            if callable(close):
                close()
            self._client = None

    def _embed(
        self,
        contents: list[str],
        *,
        timeout_seconds: float | None = None,
    ) -> list[list[float]]:
        client = self._get_client()
        content_started = perf_counter()
        try:
            sdk_contents = [
                types.Content(parts=[types.Part.from_text(text=content)])
                for content in contents
            ]
        except Exception as exc:
            raise GeminiEmbeddingRequestError(
                "Gemini embedding content could not be constructed.",
                error_code="gemini_content_build_failed",
                failure_phase="content_build",
                exception_type=_safe_exception_type(exc),
                elapsed_ms=_elapsed_ms(content_started),
            ) from None

        request_started = perf_counter()
        try:
            response = client.models.embed_content(
                model=self._model,
                contents=sdk_contents,
                config=types.EmbedContentConfig(
                    output_dimensionality=self._dimensions,
                    http_options=types.HttpOptions(
                        timeout=_request_timeout_milliseconds(
                            self._timeout_milliseconds,
                            timeout_seconds,
                        ),
                        retry_options=types.HttpRetryOptions(attempts=1),
                    ),
                ),
            )
        except Exception as exc:
            (
                error_code,
                provider_http_status,
                exception_type,
            ) = _classify_request_error(exc)
            raise GeminiEmbeddingRequestError(
                "Gemini embedding request failed.",
                error_code=error_code,
                failure_phase="sdk_call",
                provider_http_status=provider_http_status,
                exception_type=exception_type,
                elapsed_ms=_elapsed_ms(request_started),
            ) from None

        validation_started = perf_counter()
        try:
            return self._validate_response(
                response,
                expected_count=len(contents),
            )
        except InvalidEmbeddingResponseError as exc:
            raise InvalidEmbeddingResponseError(
                str(exc),
                exception_type="InvalidEmbeddingResponseError",
                elapsed_ms=_elapsed_ms(validation_started),
            ) from None
        except Exception as exc:
            raise InvalidEmbeddingResponseError(
                "Gemini returned an invalid embedding response.",
                exception_type=_safe_exception_type(exc),
                elapsed_ms=_elapsed_ms(validation_started),
            ) from None

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        started = perf_counter()
        if not self._api_key:
            raise GeminiEmbeddingConfigurationError(
                "Gemini API key is not configured.",
                elapsed_ms=_elapsed_ms(started),
            )
        try:
            self._client = self._client_factory(
                api_key=self._api_key,
                http_options=types.HttpOptions(
                    timeout=self._timeout_milliseconds,
                    retry_options=types.HttpRetryOptions(attempts=1),
                ),
            )
        except Exception as exc:
            raise GeminiEmbeddingConfigurationError(
                "Gemini client could not be created.",
                exception_type=_safe_exception_type(exc),
                elapsed_ms=_elapsed_ms(started),
            ) from None
        return self._client

    def _validate_response(
        self,
        response: object,
        *,
        expected_count: int,
    ) -> list[list[float]]:
        embeddings = getattr(response, "embeddings", None)
        if not isinstance(embeddings, Sequence) or isinstance(
            embeddings,
            (str, bytes),
        ):
            raise InvalidEmbeddingResponseError(
                "Gemini returned an invalid embedding response."
            )
        if len(embeddings) != expected_count:
            raise InvalidEmbeddingResponseError(
                "Gemini returned an unexpected number of embeddings."
            )

        vectors: list[list[float]] = []
        for embedding in embeddings:
            values = getattr(embedding, "values", None)
            if not isinstance(values, Sequence) or isinstance(
                values,
                (str, bytes),
            ):
                raise InvalidEmbeddingResponseError(
                    "Gemini returned an invalid embedding."
                )
            if len(values) != self._dimensions:
                raise InvalidEmbeddingResponseError(
                    "Gemini returned an embedding with invalid dimensions."
                )
            vector: list[float] = []
            for value in values:
                if isinstance(value, bool) or not isinstance(value, Real):
                    raise InvalidEmbeddingResponseError(
                        "Gemini returned a nonnumeric embedding value."
                    )
                normalized_value = float(value)
                if not isfinite(normalized_value):
                    raise InvalidEmbeddingResponseError(
                        "Gemini returned a non-finite embedding value."
                    )
                vector.append(normalized_value)
            vectors.append(vector)
        return vectors


def _classify_request_error(
    error: Exception,
) -> tuple[str, int | None, str | None]:
    """Return a safe category without inspecting provider error text."""

    provider_http_status = _safe_provider_http_status(error)
    exception_type = _safe_exception_type(error)
    if isinstance(error, (TimeoutError, httpx.TimeoutException)) or (
        provider_http_status in {408, 504}
    ):
        return "gemini_timeout", provider_http_status, exception_type
    if isinstance(error, httpx.ConnectError):
        return (
            "gemini_network_connect_failed",
            provider_http_status,
            exception_type,
        )
    if provider_http_status == 429:
        return "gemini_rate_limit", provider_http_status, exception_type
    if provider_http_status in {401, 403}:
        return (
            "gemini_auth_or_permission",
            provider_http_status,
            exception_type,
        )
    if provider_http_status == 413:
        return "gemini_input_limit", provider_http_status, exception_type
    if isinstance(error, (ValueError, TypeError)):
        return (
            "gemini_sdk_validation_failed",
            provider_http_status,
            exception_type,
        )
    return "gemini_request_failed", provider_http_status, exception_type


def _safe_exception_type(error: Exception) -> str | None:
    """Return an allowlisted type label without exposing exception details."""

    if isinstance(error, genai_errors.ClientError):
        return "ClientError"
    if isinstance(error, genai_errors.ServerError):
        return "ServerError"
    if isinstance(error, httpx.ConnectTimeout):
        return "ConnectTimeout"
    if isinstance(error, httpx.ReadTimeout):
        return "ReadTimeout"
    if isinstance(error, httpx.WriteTimeout):
        return "WriteTimeout"
    if isinstance(error, httpx.PoolTimeout):
        return "PoolTimeout"
    if isinstance(error, TimeoutError):
        return "TimeoutError"
    if isinstance(error, httpx.ConnectError):
        return "ConnectError"
    if isinstance(error, ValueError):
        return "ValueError"
    if isinstance(error, TypeError):
        return "TypeError"
    return None


def _safe_provider_http_status(error: Exception) -> int | None:
    """Read only the verified google-genai APIError.code field."""

    if not isinstance(error, genai_errors.APIError):
        return None
    code = error.code
    if (
        isinstance(code, bool)
        or not isinstance(code, int)
        or code not in _SAFE_PROVIDER_HTTP_STATUSES
    ):
        return None
    return code


def _elapsed_ms(started: float) -> float:
    return round(max(0.0, (perf_counter() - started) * 1000), 3)


def _request_timeout_milliseconds(
    configured_timeout_milliseconds: int,
    remaining_seconds: float | None,
) -> int:
    if remaining_seconds is None:
        return configured_timeout_milliseconds
    if (
        isinstance(remaining_seconds, bool)
        or not isinstance(remaining_seconds, Real)
        or not isfinite(float(remaining_seconds))
        or float(remaining_seconds) <= 0
    ):
        raise InvalidEmbeddingInputError(
            "Embedding request deadline has expired."
        )
    remaining_milliseconds = max(1, int(float(remaining_seconds) * 1_000))
    return min(configured_timeout_milliseconds, remaining_milliseconds)
