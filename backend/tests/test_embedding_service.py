"""Unit tests for Gemini embeddings without external API calls."""

from __future__ import annotations

import importlib
from dataclasses import replace
from math import inf, nan
from types import SimpleNamespace
from typing import Any

import pytest
import httpx
from google.genai import errors as genai_errors

from app.core.config import (
    DEFAULT_GEMINI_EMBEDDING_MODEL,
    _load_gemini_api_key,
    _load_gemini_embedding_model,
    get_settings,
)
from app.services.rag import embedding_service as embedding_module
from app.services.rag.embedding_service import (
    DOCUMENT_TEMPLATE,
    QUERY_TEMPLATE,
    GeminiEmbeddingConfigurationError,
    GeminiEmbeddingRequestError,
    GeminiEmbeddingService,
    InvalidEmbeddingInputError,
    InvalidEmbeddingResponseError,
)


DIMENSIONS = 768
TEST_API_KEY = "test-only-gemini-key-never-sent"


def fake_vector(marker: float = 0.0) -> list[float]:
    values = [0.0] * DIMENSIONS
    values[0] = marker
    return values


def response_with(*vectors: list[float]) -> SimpleNamespace:
    return SimpleNamespace(
        embeddings=[SimpleNamespace(values=vector) for vector in vectors]
    )


class FakeModels:
    def __init__(
        self,
        *,
        response: object | None = None,
        error: Exception | None = None,
    ) -> None:
        self.response = response
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def embed_content(self, **kwargs: Any) -> object:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.response


class FakeClient:
    def __init__(self, models: FakeModels) -> None:
        self.models = models


def make_settings(**overrides: object):
    return replace(
        get_settings(),
        gemini_api_key=TEST_API_KEY,
        gemini_embedding_model=DEFAULT_GEMINI_EMBEDDING_MODEL,
        gemini_embedding_dimensions=DIMENSIONS,
        **overrides,
    )


def make_service(models: FakeModels) -> GeminiEmbeddingService:
    return GeminiEmbeddingService(
        make_settings(),
        client=FakeClient(models),
    )


def requested_texts(call: dict[str, Any]) -> list[str]:
    return [content.parts[0].text for content in call["contents"]]


def test_gemini_config_reads_key_and_model_without_exposing_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", TEST_API_KEY)
    monkeypatch.delenv("GEMINI_EMBEDDING_MODEL", raising=False)

    assert _load_gemini_api_key() == TEST_API_KEY
    assert _load_gemini_embedding_model() == "gemini-embedding-2"
    assert TEST_API_KEY not in repr(make_settings())


def test_embedding_one_document_succeeds() -> None:
    models = FakeModels(response=response_with(fake_vector(1.0)))
    service = make_service(models)

    result = service.embed_documents(["Trí tuệ nhân tạo là gì?"])

    assert result == [fake_vector(1.0)]
    call = models.calls[0]
    assert call["model"] == "gemini-embedding-2"
    assert requested_texts(call) == [
        DOCUMENT_TEMPLATE.format(text="Trí tuệ nhân tạo là gì?")
    ]
    assert call["config"].output_dimensionality == DIMENSIONS
    assert call["config"].task_type is None


def test_embedding_multiple_documents_preserves_order() -> None:
    models = FakeModels(
        response=response_with(
            fake_vector(1.0),
            fake_vector(2.0),
            fake_vector(3.0),
        )
    )
    service = make_service(models)
    texts = ["Phần một", "Phần hai", "Phần ba"]

    result = service.embed_documents(texts)

    assert [vector[0] for vector in result] == [1.0, 2.0, 3.0]
    assert requested_texts(models.calls[0]) == [
        DOCUMENT_TEMPLATE.format(text=text) for text in texts
    ]


def test_query_embedding_succeeds_with_consistent_configuration() -> None:
    models = FakeModels(response=response_with(fake_vector(4.0)))
    service = make_service(models)

    result = service.embed_query("Học máy hoạt động như thế nào?")

    assert result == fake_vector(4.0)
    call = models.calls[0]
    assert requested_texts(call) == [
        QUERY_TEMPLATE.format(query="Học máy hoạt động như thế nào?")
    ]
    assert call["config"].output_dimensionality == DIMENSIONS
    assert call["config"].task_type is None


@pytest.mark.parametrize(
    ("method", "value"),
    [
        ("documents", []),
        ("documents", [""]),
        ("documents", ["   "]),
        ("documents", ["\n\n"]),
        ("documents", ["hợp lệ", "\t"]),
        ("query", ""),
        ("query", "   "),
    ],
)
def test_empty_text_is_rejected_without_calling_gemini(
    method: str,
    value: object,
) -> None:
    models = FakeModels(response=response_with(fake_vector()))
    service = make_service(models)

    with pytest.raises(InvalidEmbeddingInputError):
        if method == "documents":
            service.embed_documents(value)
        else:
            service.embed_query(value)
    assert models.calls == []


def test_query_embedding_timeout_is_capped_by_remaining_deadline() -> None:
    models = FakeModels(response=response_with(fake_vector(4.0)))
    service = make_service(models)

    service.embed_query("Cau hoi", timeout_seconds=2.25)

    assert models.calls[0]["config"].http_options.timeout == 2_250


def test_query_embedding_keeps_configured_timeout_when_budget_is_larger() -> None:
    models = FakeModels(response=response_with(fake_vector(4.0)))
    service = make_service(models)

    service.embed_query("Cau hoi", timeout_seconds=90)

    assert models.calls[0]["config"].http_options.timeout == 30_000


def test_input_validation_failure_has_safe_diagnostics() -> None:
    models = FakeModels(response=response_with(fake_vector()))

    with pytest.raises(InvalidEmbeddingInputError) as captured:
        make_service(models).embed_documents(["   "])

    assert captured.value.error_code == "gemini_input_validation_failed"
    assert captured.value.failure_phase == "input_validation"
    assert captured.value.exception_type == "InvalidEmbeddingInputError"
    assert isinstance(captured.value.elapsed_ms, float)
    assert models.calls == []


def test_client_creation_failure_has_safe_diagnostics() -> None:
    def failing_factory(**kwargs: Any) -> None:
        raise ValueError("private client detail")

    service = GeminiEmbeddingService(
        make_settings(),
        client_factory=failing_factory,
    )

    with pytest.raises(GeminiEmbeddingConfigurationError) as captured:
        service.embed_documents(["Nội dung"])

    assert captured.value.error_code == "gemini_client_creation_failed"
    assert captured.value.failure_phase == "client_creation"
    assert captured.value.exception_type == "ValueError"
    assert isinstance(captured.value.elapsed_ms, float)


def test_content_build_failure_has_safe_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    models = FakeModels(response=response_with(fake_vector()))
    service = make_service(models)

    def fail_content_build(*, text: str) -> None:
        raise TypeError("private content detail")

    monkeypatch.setattr(
        embedding_module.types.Part,
        "from_text",
        fail_content_build,
    )

    with pytest.raises(GeminiEmbeddingRequestError) as captured:
        service.embed_documents(["Nội dung"])

    assert captured.value.error_code == "gemini_content_build_failed"
    assert captured.value.failure_phase == "content_build"
    assert captured.value.exception_type == "TypeError"
    assert isinstance(captured.value.elapsed_ms, float)
    assert models.calls == []


def test_sdk_validation_failure_has_safe_diagnostics() -> None:
    models = FakeModels(error=ValueError("private SDK validation detail"))

    with pytest.raises(GeminiEmbeddingRequestError) as captured:
        make_service(models).embed_documents(["Nội dung"])

    assert captured.value.error_code == "gemini_sdk_validation_failed"
    assert captured.value.failure_phase == "sdk_call"
    assert captured.value.exception_type == "ValueError"
    assert captured.value.provider_http_status is None


def test_network_connect_failure_has_safe_diagnostics() -> None:
    models = FakeModels(error=httpx.ConnectError("private network detail"))

    with pytest.raises(GeminiEmbeddingRequestError) as captured:
        make_service(models).embed_documents(["Nội dung"])

    assert captured.value.error_code == "gemini_network_connect_failed"
    assert captured.value.failure_phase == "sdk_call"
    assert captured.value.exception_type == "ConnectError"
    assert captured.value.provider_http_status is None


def test_sdk_call_elapsed_time_covers_only_sdk_phase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    models = FakeModels(error=ValueError("private SDK validation detail"))
    service = make_service(models)
    clock = iter((1.0, 2.0, 10.0, 10.25))
    monkeypatch.setattr(embedding_module, "perf_counter", lambda: next(clock))

    with pytest.raises(GeminiEmbeddingRequestError) as captured:
        service.embed_documents(["Nội dung"])

    assert captured.value.failure_phase == "sdk_call"
    assert captured.value.elapsed_ms == 250.0


@pytest.mark.parametrize("size", [767, 769])
def test_wrong_embedding_dimensions_are_rejected(size: int) -> None:
    models = FakeModels(response=response_with([0.0] * size))

    with pytest.raises(InvalidEmbeddingResponseError):
        make_service(models).embed_documents(["Nội dung"])


@pytest.mark.parametrize("invalid_value", [nan, inf, -inf])
def test_non_finite_embedding_values_are_rejected(
    invalid_value: float,
) -> None:
    vector = fake_vector()
    vector[10] = invalid_value
    models = FakeModels(response=response_with(vector))

    with pytest.raises(InvalidEmbeddingResponseError):
        make_service(models).embed_query("Câu hỏi")


@pytest.mark.parametrize(
    "response",
    [
        SimpleNamespace(),
        SimpleNamespace(embeddings=None),
        SimpleNamespace(embeddings=[]),
        SimpleNamespace(embeddings=[SimpleNamespace()]),
    ],
)
def test_missing_embedding_response_is_rejected(response: object) -> None:
    models = FakeModels(response=response)

    with pytest.raises(InvalidEmbeddingResponseError):
        make_service(models).embed_documents(["Nội dung"])


def test_timeout_is_reported_as_safe_request_error() -> None:
    models = FakeModels(error=TimeoutError("request timed out"))

    with pytest.raises(
        GeminiEmbeddingRequestError,
        match="Gemini embedding request failed",
    ):
        make_service(models).embed_query("Câu hỏi")


def test_rate_limit_or_api_error_is_reported_safely() -> None:
    models = FakeModels(error=RuntimeError("429 quota exceeded"))

    with pytest.raises(GeminiEmbeddingRequestError) as captured:
        make_service(models).embed_documents(["Nội dung"])

    assert "429" not in str(captured.value)
    assert "quota" not in str(captured.value)


@pytest.mark.parametrize(
    ("provider_error", "error_code", "provider_http_status"),
    [
        (httpx.ReadTimeout("private timeout detail"), "gemini_timeout", None),
        (
            genai_errors.ClientError(429, {"message": "private quota detail"}),
            "gemini_rate_limit",
            429,
        ),
        (
            genai_errors.ClientError(403, {"message": "private auth detail"}),
            "gemini_auth_or_permission",
            403,
        ),
        (
            genai_errors.ClientError(413, {"message": "private input detail"}),
            "gemini_input_limit",
            413,
        ),
        (
            genai_errors.ClientError(400, {"message": "ambiguous detail"}),
            "gemini_request_failed",
            400,
        ),
    ],
)
def test_provider_errors_receive_safe_structured_classification(
    provider_error: Exception,
    error_code: str,
    provider_http_status: int | None,
) -> None:
    models = FakeModels(error=provider_error)

    with pytest.raises(GeminiEmbeddingRequestError) as captured:
        make_service(models).embed_documents(["Nội dung"])

    assert captured.value.error_code == error_code
    assert captured.value.provider_http_status == provider_http_status
    assert "private" not in str(captured.value)


def test_api_key_is_never_exposed_by_request_errors() -> None:
    models = FakeModels(error=RuntimeError(f"bad key: {TEST_API_KEY}"))

    with pytest.raises(GeminiEmbeddingRequestError) as captured:
        make_service(models).embed_query("Câu hỏi")

    assert TEST_API_KEY not in str(captured.value)
    assert TEST_API_KEY not in repr(captured.value)


def test_timeout_metadata_is_safe_and_phase_specific() -> None:
    models = FakeModels(error=TimeoutError("private timeout detail"))

    with pytest.raises(GeminiEmbeddingRequestError) as captured:
        make_service(models).embed_query("safe query")

    assert captured.value.error_code == "gemini_timeout"
    assert captured.value.failure_phase == "sdk_call"
    assert captured.value.exception_type == "TimeoutError"
    assert isinstance(captured.value.elapsed_ms, float)


def test_invalid_response_metadata_is_safe_and_phase_specific() -> None:
    models = FakeModels(response=SimpleNamespace(embeddings=[]))

    with pytest.raises(InvalidEmbeddingResponseError) as captured:
        make_service(models).embed_documents(["safe content"])

    assert captured.value.error_code == "gemini_invalid_response"
    assert captured.value.failure_phase == "response_validation"
    assert captured.value.exception_type == "InvalidEmbeddingResponseError"
    assert isinstance(captured.value.elapsed_ms, float)


def test_client_creation_is_lazy_and_configures_timeout_without_retries() -> None:
    models = FakeModels(response=response_with(fake_vector()))
    client = FakeClient(models)
    factory_calls: list[dict[str, Any]] = []

    def client_factory(**kwargs: Any) -> FakeClient:
        factory_calls.append(kwargs)
        return client

    service = GeminiEmbeddingService(
        make_settings(),
        client_factory=client_factory,
    )
    assert factory_calls == []

    service.embed_query("Câu hỏi")

    assert len(factory_calls) == 1
    assert factory_calls[0]["api_key"] == TEST_API_KEY
    http_options = factory_calls[0]["http_options"]
    assert http_options.timeout == 30_000
    assert http_options.retry_options.attempts == 1


def test_importing_module_never_creates_a_gemini_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def forbidden_client_creation(**kwargs: Any) -> None:
        nonlocal calls
        calls += 1
        raise AssertionError("Import must not create a Gemini client.")

    monkeypatch.setattr(embedding_module.genai, "Client", forbidden_client_creation)

    importlib.reload(embedding_module)

    assert calls == 0
