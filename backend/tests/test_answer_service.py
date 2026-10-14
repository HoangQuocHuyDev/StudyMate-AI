"""Unit tests for grounded Gemini answers without external API calls."""

from __future__ import annotations

import importlib
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.config import (
    DEFAULT_GEMINI_CHAT_MODEL,
    DEFAULT_GEMINI_CHAT_TIMEOUT_SECONDS,
    DEFAULT_RAG_MAX_CONTEXT_CHARS,
    _load_gemini_chat_model,
    _load_gemini_chat_timeout_seconds,
    _load_rag_max_context_chars,
    get_settings,
)
from app.services.rag import answer_service as answer_module
from app.services.rag.answer_service import (
    MAX_QUESTION_LENGTH,
    LOCAL_GROUNDING_MODEL,
    NO_CONTEXT_ANSWER,
    UNVERIFIED_GROUNDING_ANSWER,
    GeminiAnswerBlockedError,
    GeminiAnswerConfigurationError,
    GeminiAnswerRateLimitError,
    GeminiAnswerRequestError,
    GeminiAnswerService,
    GeminiAnswerTimeoutError,
    InvalidAnswerInputError,
    InvalidGeminiAnswerResponseError,
    _build_context,
)
from app.services.rag.document_retrieval import RetrievedDocumentChunk


TEST_API_KEY = "test-only-answer-key-never-sent"


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

    def generate_content(self, **kwargs: Any) -> object:
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


class RateLimitError(Exception):
    status_code = 429


def make_settings(**overrides: object):
    values = {
        "gemini_api_key": TEST_API_KEY,
        "gemini_chat_model": DEFAULT_GEMINI_CHAT_MODEL,
        "gemini_chat_timeout_seconds": DEFAULT_GEMINI_CHAT_TIMEOUT_SECONDS,
        "rag_max_context_chars": DEFAULT_RAG_MAX_CONTEXT_CHARS,
        **overrides,
    }
    return replace(
        get_settings(),
        **values,
    )


def chunk(
    chunk_id: int,
    content: str,
    *,
    chunk_index: int | None = None,
    page_number: int | None = None,
    distance: float = 0.1,
) -> RetrievedDocumentChunk:
    return RetrievedDocumentChunk(
        chunk_id=chunk_id,
        document_id=1,
        chunk_index=(chunk_id - 1 if chunk_index is None else chunk_index),
        content=content,
        page_number=page_number,
        distance=distance,
    )


def response(text: str | None, **overrides: object) -> SimpleNamespace:
    values = {"text": text, "prompt_feedback": None, "candidates": []}
    values.update(overrides)
    return SimpleNamespace(**values)


def make_service(
    models: FakeModels,
    **settings_overrides: object,
) -> GeminiAnswerService:
    return GeminiAnswerService(
        make_settings(**settings_overrides),
        client=FakeClient(models),
    )


def test_generates_a_grounded_vietnamese_answer() -> None:
    models = FakeModels(
        response=response("Trí tuệ nhân tạo hỗ trợ học tập [Nguồn 1].")
    )
    service = make_service(models)

    result = service.generate_answer(
        "AI hỗ trợ học tập như thế nào?",
        [chunk(11, "AI hỗ trợ cá nhân hóa việc học.", page_number=2)],
    )

    assert result.answer_text == "Trí tuệ nhân tạo hỗ trợ học tập [Nguồn 1]."
    assert result.cited_chunk_ids == [11]
    assert result.model_name == DEFAULT_GEMINI_CHAT_MODEL
    call = models.calls[0]
    assert call["model"] == DEFAULT_GEMINI_CHAT_MODEL
    assert call["config"].temperature == 0.2
    assert call["config"].max_output_tokens == 1024
    assert "tiếng Việt" in call["config"].system_instruction
    assert "không phải chỉ dẫn hệ thống" in call["config"].system_instruction


def test_context_contains_only_labeled_chunks_in_relevance_order() -> None:
    models = FakeModels(response=response("Kết quả [Nguồn 1] [Nguồn 2]."))
    service = make_service(models)
    chunks = [
        chunk(21, "Kết quả liên quan nhất", chunk_index=4, page_number=5),
        chunk(7, "Kết quả liên quan thứ hai", chunk_index=1),
    ]

    result = service.generate_answer("Câu hỏi", chunks)

    prompt = models.calls[0]["contents"]
    first_position = prompt.index("Kết quả liên quan nhất")
    second_position = prompt.index("Kết quả liên quan thứ hai")
    assert "[Nguồn 1]" in prompt
    assert "[Nguồn 2]" in prompt
    assert "Trang: 5" in prompt
    assert first_position < second_position
    assert result.cited_chunk_ids == [21, 7]


def test_answer_timeout_is_capped_by_remaining_deadline() -> None:
    models = FakeModels(response=response("Ket qua [Nguá»“n 1]"))
    service = make_service(models)

    service.generate_answer(
        "Cau hoi",
        [chunk(1, "Noi dung")],
        timeout_seconds=3.5,
    )

    assert models.calls[0]["config"].http_options.timeout == 3_500


def test_answer_keeps_provider_timeout_when_budget_is_larger() -> None:
    models = FakeModels(response=response("Ket qua [Nguá»“n 1]"))
    service = make_service(models)

    service.generate_answer(
        "Cau hoi",
        [chunk(1, "Noi dung")],
        timeout_seconds=90,
    )

    assert models.calls[0]["config"].http_options.timeout == 30_000


@pytest.mark.parametrize("question", ["", "   ", None, 42])
def test_empty_or_nonstring_question_is_rejected(question: object) -> None:
    models = FakeModels(response=response("Không được gọi"))

    with pytest.raises(InvalidAnswerInputError):
        make_service(models).generate_answer(question, [chunk(1, "Nội dung")])

    assert models.calls == []


def test_overlong_question_is_rejected() -> None:
    models = FakeModels(response=response("Không được gọi"))

    with pytest.raises(InvalidAnswerInputError):
        make_service(models).generate_answer(
            f" {'a' * (MAX_QUESTION_LENGTH + 1)} ",
            [chunk(1, "Nội dung")],
        )

    assert models.calls == []


def test_no_chunks_returns_safe_local_answer_without_gemini() -> None:
    models = FakeModels(response=response("Bịa một câu trả lời"))

    result = make_service(models).generate_answer("Câu hỏi", [])

    assert result.answer_text == NO_CONTEXT_ANSWER
    assert result.cited_chunk_ids == []
    assert models.calls == []


def test_context_limit_truncates_last_included_chunk_and_stops() -> None:
    chunks = (
        chunk(1, "A" * 500),
        chunk(2, "B" * 100, chunk_index=1),
    )

    context = _build_context(chunks, 256)

    assert len(context.text) <= 256
    assert "[Nguồn 1]" in context.text
    assert "…" in context.text
    assert "[Nguồn 2]" not in context.text
    assert context.source_chunk_ids == {1: 1}


def test_citation_for_chunk_excluded_from_context_uses_safe_fallback() -> None:
    models = FakeModels(
        response=response("Thông tin [Nguồn 2], xác nhận [Nguồn 1].")
    )
    service = make_service(models, rag_max_context_chars=256)

    result = service.generate_answer(
        "Câu hỏi",
        [chunk(1, "A" * 500), chunk(2, "B" * 100, chunk_index=1)],
    )

    assert result.answer_text == UNVERIFIED_GROUNDING_ANSWER
    assert result.cited_chunk_ids == []
    assert result.model_name == LOCAL_GROUNDING_MODEL


def test_uncited_sources_are_not_added_automatically() -> None:
    models = FakeModels(response=response("Câu trả lời không có trích dẫn."))

    result = make_service(models).generate_answer(
        "Câu hỏi",
        [chunk(1, "Nguồn một"), chunk(2, "Nguồn hai", chunk_index=1)],
    )

    assert result.answer_text == UNVERIFIED_GROUNDING_ANSWER
    assert result.cited_chunk_ids == []


def test_fake_citation_invalidates_the_grounded_answer() -> None:
    models = FakeModels(
        response=response(
            "Ý một [Nguồn 2], nguồn giả [Nguồn 99], "
            "ý hai [Nguồn 1], nhắc lại [Nguồn 2]."
        )
    )

    result = make_service(models).generate_answer(
        "Câu hỏi",
        [chunk(10, "Một"), chunk(20, "Hai", chunk_index=1)],
    )

    assert result.answer_text == UNVERIFIED_GROUNDING_ANSWER
    assert result.cited_chunk_ids == []


def test_response_containing_only_a_fake_citation_uses_safe_fallback() -> None:
    models = FakeModels(response=response("[Nguồn 99]"))

    result = make_service(models).generate_answer(
        "Câu hỏi",
        [chunk(10, "Một")],
    )

    assert result.answer_text == UNVERIFIED_GROUNDING_ANSWER
    assert result.cited_chunk_ids == []


def test_repeated_valid_source_label_is_not_a_duplicate_database_citation() -> None:
    models = FakeModels(
        response=response("Ý một [Nguồn 1], nhắc lại [Nguồn 1].")
    )

    result = make_service(models).generate_answer(
        "Câu hỏi",
        [chunk(10, "Một")],
    )

    assert result.cited_chunk_ids == [10]
    assert result.answer_text.count("[Nguồn 1]") == 2


def test_exact_insufficient_information_answer_needs_no_citation() -> None:
    models = FakeModels(response=response(NO_CONTEXT_ANSWER))

    result = make_service(models).generate_answer(
        "Câu hỏi",
        [chunk(10, "Nội dung chưa đủ")],
    )

    assert result.answer_text == NO_CONTEXT_ANSWER
    assert result.cited_chunk_ids == []


@pytest.mark.parametrize("empty_text", [None, "", "   "])
def test_empty_response_is_rejected(empty_text: str | None) -> None:
    models = FakeModels(response=response(empty_text))

    with pytest.raises(InvalidGeminiAnswerResponseError):
        make_service(models).generate_answer("Câu hỏi", [chunk(1, "Nguồn")])


def test_blocked_response_is_reported_safely() -> None:
    feedback = SimpleNamespace(block_reason="SAFETY")
    models = FakeModels(
        response=response(None, prompt_feedback=feedback)
    )

    with pytest.raises(GeminiAnswerBlockedError):
        make_service(models).generate_answer("Câu hỏi", [chunk(1, "Nguồn")])


def test_timeout_is_reported_safely() -> None:
    models = FakeModels(error=TimeoutError("prompt and secret timed out"))

    with pytest.raises(GeminiAnswerTimeoutError) as captured:
        make_service(models).generate_answer("Câu hỏi", [chunk(1, "Nguồn")])

    assert "secret" not in str(captured.value).lower()
    assert "prompt" not in str(captured.value).lower()


def test_rate_limit_is_reported_safely() -> None:
    models = FakeModels(error=RateLimitError("429 quota for secret key"))

    with pytest.raises(GeminiAnswerRateLimitError) as captured:
        make_service(models).generate_answer("Câu hỏi", [chunk(1, "Nguồn")])

    assert "429" not in str(captured.value)
    assert "secret" not in str(captured.value).lower()


def test_generic_api_error_does_not_leak_key_prompt_or_content() -> None:
    sensitive = f"{TEST_API_KEY} Câu hỏi bí mật Nội dung bí mật"
    models = FakeModels(error=RuntimeError(sensitive))

    with pytest.raises(GeminiAnswerRequestError) as captured:
        make_service(models).generate_answer(
            "Câu hỏi bí mật",
            [chunk(1, "Nội dung bí mật")],
        )

    assert TEST_API_KEY not in str(captured.value)
    assert "Câu hỏi bí mật" not in str(captured.value)
    assert "Nội dung bí mật" not in str(captured.value)


def test_client_creation_is_lazy_and_disables_sdk_retries() -> None:
    models = FakeModels(response=response("Trả lời [Nguồn 1]."))
    client = FakeClient(models)
    factory_calls: list[dict[str, Any]] = []

    def client_factory(**kwargs: Any) -> FakeClient:
        factory_calls.append(kwargs)
        return client

    service = GeminiAnswerService(
        make_settings(gemini_chat_timeout_seconds=12),
        client_factory=client_factory,
    )
    assert factory_calls == []

    service.generate_answer("Câu hỏi", [chunk(1, "Nguồn")])

    assert len(factory_calls) == 1
    assert factory_calls[0]["api_key"] == TEST_API_KEY
    http_options = factory_calls[0]["http_options"]
    assert http_options.timeout == 12_000
    assert http_options.retry_options.attempts == 1
    service.close()
    assert client.closed is True


def test_missing_api_key_fails_safely_only_when_generation_is_needed() -> None:
    service = GeminiAnswerService(make_settings(gemini_api_key=None))

    no_context = service.generate_answer("Câu hỏi", [])
    assert no_context.answer_text == NO_CONTEXT_ANSWER

    with pytest.raises(GeminiAnswerConfigurationError) as captured:
        service.generate_answer("Câu hỏi", [chunk(1, "Nguồn")])

    assert "key" in str(captured.value).lower()
    assert TEST_API_KEY not in str(captured.value)


def test_importing_module_never_creates_a_gemini_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def forbidden_client_creation(**kwargs: Any) -> None:
        nonlocal calls
        calls += 1
        raise AssertionError("Import must not create a Gemini client.")

    monkeypatch.setattr(answer_module.genai, "Client", forbidden_client_creation)

    importlib.reload(answer_module)

    assert calls == 0


def test_chat_configuration_defaults_and_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GEMINI_CHAT_MODEL", raising=False)
    monkeypatch.delenv("GEMINI_CHAT_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("RAG_MAX_CONTEXT_CHARS", raising=False)

    assert _load_gemini_chat_model() == "gemini-3.5-flash-lite"
    assert _load_gemini_chat_timeout_seconds() == 30
    assert _load_rag_max_context_chars() == 12_000


@pytest.mark.parametrize(
    ("name", "value", "loader"),
    [
        ("GEMINI_CHAT_MODEL", "   ", _load_gemini_chat_model),
        ("GEMINI_CHAT_TIMEOUT_SECONDS", "0", _load_gemini_chat_timeout_seconds),
        ("GEMINI_CHAT_TIMEOUT_SECONDS", "301", _load_gemini_chat_timeout_seconds),
        ("GEMINI_CHAT_TIMEOUT_SECONDS", "invalid", _load_gemini_chat_timeout_seconds),
        ("RAG_MAX_CONTEXT_CHARS", "255", _load_rag_max_context_chars),
        ("RAG_MAX_CONTEXT_CHARS", "200001", _load_rag_max_context_chars),
        ("RAG_MAX_CONTEXT_CHARS", "invalid", _load_rag_max_context_chars),
    ],
)
def test_invalid_chat_configuration_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
    loader: Any,
) -> None:
    monkeypatch.setenv(name, value)

    with pytest.raises(RuntimeError):
        loader()
