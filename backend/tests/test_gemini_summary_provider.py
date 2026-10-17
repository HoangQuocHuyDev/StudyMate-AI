"""Unit tests for the lazy Gemini summary provider."""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest
from google.genai import errors as genai_errors

from app.services.summary.gemini_summary import (
    GeminiSummaryAuthenticationError,
    GeminiSummaryBlockedError,
    GeminiSummaryConfigurationError,
    GeminiSummaryInvalidRequestError,
    GeminiSummaryModelUnavailableError,
    GeminiSummaryNetworkError,
    GeminiSummaryProvider,
    GeminiSummaryRateLimitError,
    GeminiSummaryTimeoutError,
    GeminiSummaryUpstreamUnavailableError,
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


class ScriptedModels:
    def __init__(self, results: list[object]) -> None:
        self.results = list(results)
        self.calls: list[dict[str, object]] = []

    def generate_content(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class ManualClock:
    def __init__(self) -> None:
        self.value = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.value += seconds


def settings(
    api_key: str | None = "test-key",
    *,
    model: str = "gemini-test-model",
    timeout_seconds: int = 12,
) -> SimpleNamespace:
    return SimpleNamespace(
        gemini_api_key=api_key,
        gemini_chat_model=model,
        gemini_chat_timeout_seconds=timeout_seconds,
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
    assert created[0]["http_options"].retry_options.attempts == 1
    assert client.models.calls[0]["model"] == "gemini-test-model"
    config = client.models.calls[0]["config"]
    assert config.max_output_tokens == 512
    assert config.http_options.retry_options.attempts == 1
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
    clock = ManualClock()
    provider = GeminiSummaryProvider(
        settings(),
        client=FakeClient(models),
        clock=clock,
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


@pytest.mark.parametrize(
    ("summary_type", "expected_timeout"),
    [
        ("SHORT", 30_000),
        ("STANDARD", 30_000),
        ("DETAILED", 60_000),
    ],
)
def test_request_timeout_is_selected_by_summary_type(
    summary_type: str,
    expected_timeout: int,
) -> None:
    models = FakeModels()
    provider = GeminiSummaryProvider(
        settings(timeout_seconds=30),
        client=FakeClient(models),
    )
    provider.generate_summary(
        "Document",
        summary_type,  # type: ignore[arg-type]
        stage="FINAL",
    )
    assert models.calls[0]["config"].http_options.timeout == expected_timeout


def test_detailed_timeout_is_capped_by_remaining_overall_deadline() -> None:
    models = FakeModels()
    clock = ManualClock()
    provider = GeminiSummaryProvider(
        settings(timeout_seconds=30),
        client=FakeClient(models),
        clock=clock,
    )
    provider.generate_summary(
        "Document",
        "DETAILED",
        stage="MAP",
        timeout_seconds=17.25,
    )
    assert models.calls[0]["config"].http_options.timeout == 17_250


def test_flash_lite_omits_unsupported_sampling_parameters() -> None:
    models = FakeModels()
    provider = GeminiSummaryProvider(
        settings(model="gemini-3.5-flash-lite"),
        client=FakeClient(models),
    )
    provider.generate_summary("Document", "STANDARD", stage="FINAL")
    config = models.calls[0]["config"]
    assert config.temperature is None
    assert config.top_p is None
    assert config.top_k is None


def test_other_models_keep_existing_temperature_configuration() -> None:
    models = FakeModels()
    provider = GeminiSummaryProvider(settings(), client=FakeClient(models))
    provider.generate_summary("Document", "STANDARD", stage="FINAL")
    assert models.calls[0]["config"].temperature == 0.2


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
        (
            genai_errors.ClientError(
                429,
                {
                    "message": "secret api key and document",
                    "status": "RESOURCE_EXHAUSTED",
                },
            ),
            GeminiSummaryRateLimitError,
        ),
    ],
)
def test_provider_errors_are_classified_without_secrets(
    error: Exception,
    expected: type[Exception],
) -> None:
    provider = GeminiSummaryProvider(
        settings(), client=FakeClient(FakeModels(error=error))
    )
    with pytest.raises(expected) as captured:
        provider.generate_summary("Nội dung", "SHORT", stage="FINAL")
    assert "secret" not in str(captured.value).lower()


@pytest.mark.parametrize(
    ("status_code", "status", "expected"),
    [
        (400, "INVALID_ARGUMENT", GeminiSummaryInvalidRequestError),
        (401, "UNAUTHENTICATED", GeminiSummaryAuthenticationError),
        (403, "PERMISSION_DENIED", GeminiSummaryAuthenticationError),
        (404, "NOT_FOUND", GeminiSummaryModelUnavailableError),
        (429, "RESOURCE_EXHAUSTED", GeminiSummaryRateLimitError),
        (503, "UNAVAILABLE", GeminiSummaryUpstreamUnavailableError),
        (504, "DEADLINE_EXCEEDED", GeminiSummaryTimeoutError),
    ],
)
def test_sdk_errors_are_classified_from_structured_fields(
    status_code: int,
    status: str,
    expected: type[Exception],
) -> None:
    error_type = (
        genai_errors.ClientError
        if status_code < 500
        else genai_errors.ServerError
    )
    error = error_type(
        status_code,
        {"message": "secret api key and document", "status": status},
    )
    provider = GeminiSummaryProvider(
        settings(), client=FakeClient(FakeModels(error=error))
    )
    with pytest.raises(expected) as captured:
        provider.generate_summary("Document", "SHORT", stage="FINAL")
    assert "secret" not in str(captured.value).lower()


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (httpx.ReadTimeout("secret document"), GeminiSummaryTimeoutError),
        (httpx.ConnectError("secret document"), GeminiSummaryNetworkError),
    ],
)
def test_transport_errors_are_classified_by_type(
    error: Exception,
    expected: type[Exception],
) -> None:
    provider = GeminiSummaryProvider(
        settings(), client=FakeClient(FakeModels(error=error))
    )
    with pytest.raises(expected):
        provider.generate_summary("Document", "SHORT", stage="MAP")


def test_failure_log_is_structured_and_does_not_expose_sensitive_data(
    caplog: pytest.LogCaptureFixture,
) -> None:
    error = genai_errors.ClientError(
        400,
        {
            "message": "api-key-secret provider-message-secret",
            "status": "INVALID_ARGUMENT",
        },
    )
    provider = GeminiSummaryProvider(
        settings(api_key="api-key-secret"),
        client=FakeClient(FakeModels(error=error)),
    )

    with caplog.at_level("WARNING"), pytest.raises(
        GeminiSummaryInvalidRequestError
    ):
        provider.generate_summary(
            "chunk-content-secret",
            "DETAILED",
            stage="REDUCE",
        )

    event = json.loads(caplog.messages[-1])
    assert event == {
        "event": "gemini_summary_request_failed",
        "stage": "REDUCE",
        "model": "gemini-test-model",
        "request_index": 1,
        "attempt": 1,
        "max_attempts": 3,
        "elapsed_ms": event["elapsed_ms"],
        "exception_type": "GeminiClientError",
        "sdk_error_code": 400,
        "sdk_error_status": "INVALID_ARGUMENT",
        "error_code": "gemini_invalid_request",
        "will_retry": False,
        "retry_wait_ms": None,
    }
    assert event["elapsed_ms"] >= 0
    combined_log = " ".join(caplog.messages).lower()
    assert "api-key-secret" not in combined_log
    assert "provider-message-secret" not in combined_log
    assert "chunk-content-secret" not in combined_log


@pytest.mark.parametrize(
    ("summary_type", "expected_tokens"),
    [("SHORT", 512), ("STANDARD", 1_024), ("DETAILED", 2_048)],
)
def test_all_summary_modes_keep_their_output_limits(
    summary_type: str,
    expected_tokens: int,
) -> None:
    models = FakeModels()
    provider = GeminiSummaryProvider(
        settings(model="gemini-3.5-flash-lite"),
        client=FakeClient(models),
    )
    provider.generate_summary(
        "Document",
        summary_type,  # type: ignore[arg-type]
        stage="FINAL",
    )
    assert models.calls[0]["config"].max_output_tokens == expected_tokens


def _server_error(code: int = 503) -> genai_errors.ServerError:
    status = "UNAVAILABLE" if code == 503 else "INTERNAL"
    return genai_errors.ServerError(
        code,
        {"message": "provider-secret", "status": status},
    )


@pytest.mark.parametrize("status_code", [500, 502, 503])
def test_transient_server_error_is_retried_and_recovered(
    caplog: pytest.LogCaptureFixture,
    status_code: int,
) -> None:
    models = ScriptedModels(
        [_server_error(status_code), SimpleNamespace(text="Recovered summary")]
    )
    clock = ManualClock()
    provider = GeminiSummaryProvider(
        settings(timeout_seconds=30),
        client=FakeClient(models),  # type: ignore[arg-type]
        clock=clock,
        sleep_func=clock.sleep,
        retry_delay_func=lambda attempt: 0.25 * attempt,
    )

    with caplog.at_level("INFO"):
        result = provider.generate_summary(
            "Document",
            "DETAILED",
            stage="MAP",
            timeout_seconds=120,
        )

    assert result.content == "Recovered summary"
    assert len(models.calls) == 2
    assert clock.sleeps == [0.25]
    events = [json.loads(message) for message in caplog.messages]
    assert events[0]["event"] == "gemini_summary_request_failed"
    assert events[0]["request_index"] == 1
    assert events[0]["attempt"] == 1
    assert events[0]["will_retry"] is True
    assert events[0]["retry_wait_ms"] == 250.0
    assert events[-1]["event"] == "gemini_summary_request_recovered"
    assert events[-1]["attempt"] == 2


def test_transient_503_stops_after_three_total_attempts(
    caplog: pytest.LogCaptureFixture,
) -> None:
    models = ScriptedModels([_server_error(), _server_error(), _server_error()])
    clock = ManualClock()
    provider = GeminiSummaryProvider(
        settings(),
        client=FakeClient(models),  # type: ignore[arg-type]
        clock=clock,
        sleep_func=clock.sleep,
        retry_delay_func=lambda attempt: float(attempt),
    )

    with caplog.at_level("WARNING"), pytest.raises(
        GeminiSummaryUpstreamUnavailableError
    ):
        provider.generate_summary(
            "Document",
            "STANDARD",
            stage="MAP",
            timeout_seconds=120,
        )

    assert len(models.calls) == 3
    assert clock.sleeps == [1.0, 2.0]
    events = [json.loads(message) for message in caplog.messages]
    assert [event["attempt"] for event in events] == [1, 2, 3]
    assert [event["will_retry"] for event in events] == [True, True, False]


def test_valid_short_retry_after_is_used_without_sdk_retry() -> None:
    error = genai_errors.ServerError(
        503,
        {"message": "provider-secret", "status": "UNAVAILABLE"},
        response=httpx.Response(503, headers={"Retry-After": "2"}),
    )
    models = ScriptedModels([error, SimpleNamespace(text="Recovered summary")])
    clock = ManualClock()
    provider = GeminiSummaryProvider(
        settings(),
        client=FakeClient(models),  # type: ignore[arg-type]
        clock=clock,
        sleep_func=clock.sleep,
        retry_delay_func=lambda attempt: pytest.fail("must use Retry-After"),
    )
    provider.generate_summary(
        "Document",
        "DETAILED",
        stage="MAP",
        timeout_seconds=120,
    )
    assert clock.sleeps == [2.0]
    assert all(
        call["config"].http_options.retry_options.attempts == 1
        for call in models.calls
    )


@pytest.mark.parametrize(
    ("code", "status", "expected"),
    [
        (400, "INVALID_ARGUMENT", GeminiSummaryInvalidRequestError),
        (401, "UNAUTHENTICATED", GeminiSummaryAuthenticationError),
        (403, "PERMISSION_DENIED", GeminiSummaryAuthenticationError),
        (404, "NOT_FOUND", GeminiSummaryModelUnavailableError),
        (429, "RESOURCE_EXHAUSTED", GeminiSummaryRateLimitError),
    ],
)
def test_non_transient_sdk_errors_are_not_retried(
    code: int,
    status: str,
    expected: type[Exception],
) -> None:
    models = ScriptedModels(
        [
            genai_errors.ClientError(
                code,
                {"message": "provider-secret", "status": status},
            )
        ]
    )
    provider = GeminiSummaryProvider(
        settings(),
        client=FakeClient(models),  # type: ignore[arg-type]
        sleep_func=lambda seconds: pytest.fail("must not sleep"),
    )
    with pytest.raises(expected):
        provider.generate_summary("Document", "DETAILED", stage="MAP")
    assert len(models.calls) == 1


def test_retry_does_not_start_when_deadline_cannot_cover_backoff() -> None:
    models = ScriptedModels([_server_error()])
    clock = ManualClock()
    provider = GeminiSummaryProvider(
        settings(),
        client=FakeClient(models),  # type: ignore[arg-type]
        clock=clock,
        sleep_func=clock.sleep,
        retry_delay_func=lambda attempt: 0.5,
    )
    with pytest.raises(GeminiSummaryUpstreamUnavailableError):
        provider.generate_summary(
            "Document",
            "DETAILED",
            stage="MAP",
            timeout_seconds=0.25,
        )
    assert len(models.calls) == 1
    assert clock.sleeps == []


def test_deadline_expiring_during_backoff_stops_before_next_attempt() -> None:
    models = ScriptedModels([_server_error()])
    clock = ManualClock()

    def oversleep(seconds: float) -> None:
        clock.sleeps.append(seconds)
        clock.value += 2.0

    provider = GeminiSummaryProvider(
        settings(),
        client=FakeClient(models),  # type: ignore[arg-type]
        clock=clock,
        sleep_func=oversleep,
        retry_delay_func=lambda attempt: 0.25,
    )
    with pytest.raises(GeminiSummaryTimeoutError):
        provider.generate_summary(
            "Document",
            "DETAILED",
            stage="MAP",
            timeout_seconds=1.0,
        )
    assert len(models.calls) == 1
    assert clock.sleeps == [0.25]


def test_retry_only_repeats_the_failed_logical_map_request() -> None:
    models = ScriptedModels(
        [
            SimpleNamespace(text="Map one"),
            SimpleNamespace(text="Map two"),
            _server_error(),
            SimpleNamespace(text="Map three"),
        ]
    )
    clock = ManualClock()
    provider = GeminiSummaryProvider(
        settings(),
        client=FakeClient(models),  # type: ignore[arg-type]
        clock=clock,
        sleep_func=clock.sleep,
        retry_delay_func=lambda attempt: 0.1,
    )

    provider.generate_summary("FIRST_MAP", "DETAILED", stage="MAP")
    provider.generate_summary("SECOND_MAP", "DETAILED", stage="MAP")
    provider.generate_summary("THIRD_MAP", "DETAILED", stage="MAP")

    prompts = [str(call["contents"]) for call in models.calls]
    assert sum("FIRST_MAP" in prompt for prompt in prompts) == 1
    assert sum("SECOND_MAP" in prompt for prompt in prompts) == 1
    assert sum("THIRD_MAP" in prompt for prompt in prompts) == 2
    assert len(models.calls) == 4
