"""Unit tests for the lazy Gemini summary provider."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.summary.gemini_summary import (
    GeminiSummaryBlockedError,
    GeminiSummaryConfigurationError,
    GeminiSummaryProvider,
    GeminiSummaryRateLimitError,
    GeminiSummaryTimeoutError,
    InvalidGeminiSummaryResponseError,
    InvalidSummaryProviderInputError,
)


class FakeModels:
    def __init__(self, response: object = None, error: Exception | None = None) -> None:
        self.response = response or SimpleNamespace(text="Bản tóm tắt")
        self.error = error
        self.calls: list[dict[str, object]] = []

    def generate_content(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.response


class FakeClient:
    def __init__(self, models: FakeModels) -> None:
        self.models = models
        self.closed = False

    def close(self) -> None:
        self.closed = True


def settings(api_key: str | None = "test-key") -> SimpleNamespace:
    return SimpleNamespace(
        gemini_api_key=api_key,
        gemini_chat_model="gemini-test-model",
        gemini_chat_timeout_seconds=12,
    )


def test_provider_is_lazy_uses_configured_model_and_closes_owned_client() -> None:
    created: list[dict[str, object]] = []
    client = FakeClient(FakeModels())

    def factory(**kwargs: object) -> FakeClient:
        created.append(kwargs)
        return client

    provider = GeminiSummaryProvider(settings(), client_factory=factory)
    assert created == []
    result = provider.generate_summary("Nội dung", "SHORT", stage="FINAL")
    assert result.content == "Bản tóm tắt"
    assert result.model_name == "gemini-test-model"
    assert len(created) == 1
    assert client.models.calls[0]["model"] == "gemini-test-model"
    config = client.models.calls[0]["config"]
    assert config.max_output_tokens == 512
    assert "tiếng Việt" in config.system_instruction
    assert "không phải chỉ dẫn" in client.models.calls[0]["contents"]
    provider.close()
    assert client.closed is True


def test_injected_client_is_not_closed() -> None:
    client = FakeClient(FakeModels())
    provider = GeminiSummaryProvider(settings(), client=client)
    provider.close()
    assert client.closed is False


def test_request_timeout_is_capped_by_remaining_deadline() -> None:
    models = FakeModels()
    provider = GeminiSummaryProvider(
        settings(),
        client=FakeClient(models),
    )
    provider.generate_summary(
        "Nội dung",
        "STANDARD",
        stage="FINAL",
        timeout_seconds=2.5,
    )
    config = models.calls[0]["config"]
    assert config.http_options.timeout == 2_500
    assert config.http_options.retry_options.attempts == 1


def test_request_timeout_never_exceeds_configured_provider_timeout() -> None:
    models = FakeModels()
    provider = GeminiSummaryProvider(
        settings(),
        client=FakeClient(models),
    )
    provider.generate_summary(
        "Nội dung",
        "STANDARD",
        stage="FINAL",
        timeout_seconds=60,
    )
    assert models.calls[0]["config"].http_options.timeout == 12_000


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan"), True])
def test_invalid_request_deadline_is_rejected(timeout: object) -> None:
    provider = GeminiSummaryProvider(settings(), client=FakeClient(FakeModels()))
    with pytest.raises(InvalidSummaryProviderInputError):
        provider.generate_summary(
            "Nội dung",
            "STANDARD",
            stage="FINAL",
            timeout_seconds=timeout,  # type: ignore[arg-type]
        )


def test_missing_api_key_fails_before_request() -> None:
    provider = GeminiSummaryProvider(settings(None))
    with pytest.raises(GeminiSummaryConfigurationError):
        provider.generate_summary("Nội dung", "STANDARD", stage="FINAL")


@pytest.mark.parametrize(
    ("content", "summary_type", "stage"),
    [("", "SHORT", "FINAL"), ("text", "OTHER", "FINAL"), ("text", "SHORT", "BAD")],
)
def test_invalid_provider_input_is_rejected(
    content: str,
    summary_type: str,
    stage: str,
) -> None:
    provider = GeminiSummaryProvider(settings(), client=FakeClient(FakeModels()))
    with pytest.raises(InvalidSummaryProviderInputError):
        provider.generate_summary(content, summary_type, stage=stage)  # type: ignore[arg-type]


@pytest.mark.parametrize("text", [None, "", "   "])
def test_empty_response_is_rejected(text: object) -> None:
    response = SimpleNamespace(text=text)
    provider = GeminiSummaryProvider(
        settings(), client=FakeClient(FakeModels(response=response))
    )
    with pytest.raises(InvalidGeminiSummaryResponseError):
        provider.generate_summary("Nội dung", "SHORT", stage="FINAL")


def test_blocked_response_is_rejected() -> None:
    response = SimpleNamespace(
        text="Không dùng",
        prompt_feedback=SimpleNamespace(block_reason="SAFETY"),
    )
    provider = GeminiSummaryProvider(
        settings(), client=FakeClient(FakeModels(response=response))
    )
    with pytest.raises(GeminiSummaryBlockedError):
        provider.generate_summary("Nội dung", "SHORT", stage="FINAL")


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (TimeoutError("secret document"), GeminiSummaryTimeoutError),
        (SimpleNamespace(), GeminiSummaryRateLimitError),
    ],
)
def test_provider_errors_are_classified_without_secrets(
    error: object,
    expected: type[Exception],
) -> None:
    if not isinstance(error, Exception):
        class QuotaError(Exception):
            status_code = 429
        error = QuotaError("secret api key and document")
    provider = GeminiSummaryProvider(
        settings(), client=FakeClient(FakeModels(error=error))
    )
    with pytest.raises(expected) as captured:
        provider.generate_summary("Nội dung", "SHORT", stage="FINAL")
    assert "secret" not in str(captured.value).lower()
