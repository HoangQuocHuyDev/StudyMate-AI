"""Unit tests for offset-safe semantic text chunking."""

from __future__ import annotations

import pytest

from app.services.document_extractor import ExtractedText
from app.services.text_chunker import (
    MAX_CHUNKS,
    MAX_TEXT_CHARACTERS,
    ChunkingLimitError,
    InvalidChunkConfigurationError,
    InvalidTextError,
    TextChunk,
    chunk_extracted_text,
    chunk_text,
)


def assert_chunk_invariants(source: str, chunks: list[TextChunk]) -> None:
    assert [chunk.index for chunk in chunks] == list(range(len(chunks)))
    for chunk in chunks:
        assert 0 <= chunk.start_char < chunk.end_char <= len(source)
        assert source[chunk.start_char : chunk.end_char] == chunk.text
        assert chunk.character_count == len(chunk.text)
    for previous, current in zip(chunks, chunks[1:]):
        assert current.start_char > previous.start_char
        assert current.end_char > previous.end_char
        assert current.start_char <= previous.end_char
        assert (current.start_char, current.end_char) != (
            previous.start_char,
            previous.end_char,
        )


def assert_all_characters_covered(source: str, chunks: list[TextChunk]) -> None:
    covered = [False] * len(source)
    for chunk in chunks:
        covered[chunk.start_char : chunk.end_char] = [True] * len(chunk.text)
    assert all(covered)


def extracted(
    text: str,
    *,
    file_type: str = "DOCX",
    page_count: int | None = None,
) -> ExtractedText:
    return ExtractedText(
        text=text,
        file_type=file_type,
        character_count=len(text),
        page_count=page_count,
    )


def test_short_text_produces_one_exact_chunk() -> None:
    chunks = chunk_text("Short lesson", chunk_size=20, chunk_overlap=5)

    assert [chunk.text for chunk in chunks] == ["Short lesson"]
    assert_chunk_invariants("Short lesson", chunks)


def test_text_exactly_chunk_size_produces_one_chunk() -> None:
    text = "x" * 20

    chunks = chunk_text(text, chunk_size=20, chunk_overlap=5)

    assert len(chunks) == 1
    assert chunks[0].text == text


def test_long_text_produces_multiple_chunks() -> None:
    text = "alpha beta gamma delta epsilon zeta eta theta"

    chunks = chunk_text(text, chunk_size=18, chunk_overlap=4)

    assert len(chunks) > 1
    assert all(chunk.character_count <= 18 for chunk in chunks)
    assert_chunk_invariants(text, chunks)
    assert_all_characters_covered(text, chunks)


def test_zero_overlap_makes_adjacent_chunks() -> None:
    text = "abcdefghij" * 3

    chunks = chunk_text(text, chunk_size=10, chunk_overlap=0)

    assert all(
        current.start_char == previous.end_char
        for previous, current in zip(chunks, chunks[1:])
    )
    assert "".join(chunk.text for chunk in chunks) == text


def test_positive_overlap_is_present() -> None:
    text = "abcdefghij" * 3

    chunks = chunk_text(text, chunk_size=10, chunk_overlap=3)

    assert all(
        current.start_char < previous.end_char
        for previous, current in zip(chunks, chunks[1:])
    )


def test_overlap_near_chunk_size_still_advances() -> None:
    text = "abcdefghijklmnopqrstuvwxyz"

    chunks = chunk_text(text, chunk_size=10, chunk_overlap=9)

    assert chunks[-1].end_char == len(text)
    assert_chunk_invariants(text, chunks)


def test_paragraph_boundary_has_priority() -> None:
    text = "First paragraph.\n\nSecond sentence. More words here."

    first = chunk_text(text, chunk_size=42, chunk_overlap=0)[0]

    assert first.text == "First paragraph.\n\n"


def test_sentence_boundary_has_priority_over_whitespace() -> None:
    text = "First sentence ends here. Second phrase has more words."

    first = chunk_text(text, chunk_size=40, chunk_overlap=0)[0]

    assert first.text == "First sentence ends here."


def test_whitespace_boundary_avoids_splitting_a_word() -> None:
    text = "alpha beta extraordinaryword omega"

    first = chunk_text(text, chunk_size=17, chunk_overlap=0)[0]

    assert first.text == "alpha beta "


def test_long_unbroken_string_uses_hard_character_cut() -> None:
    text = "x" * 25

    chunks = chunk_text(text, chunk_size=10, chunk_overlap=0)

    assert [len(chunk.text) for chunk in chunks] == [10, 10, 5]
    assert "".join(chunk.text for chunk in chunks) == text


def test_vietnamese_text_is_preserved() -> None:
    text = "Trí tuệ nhân tạo hỗ trợ học tập hiệu quả cho sinh viên."

    chunks = chunk_text(text, chunk_size=24, chunk_overlap=5)

    assert_chunk_invariants(text, chunks)
    assert_all_characters_covered(text, chunks)
    assert "ệ" in "".join(chunk.text for chunk in chunks)


def test_crlf_boundaries_preserve_original_offsets() -> None:
    text = "Dòng một\r\nDòng hai\r\nDòng ba"

    chunks = chunk_text(text, chunk_size=15, chunk_overlap=3)

    assert_chunk_invariants(text, chunks)
    assert_all_characters_covered(text, chunks)


def test_multiple_newlines_are_not_normalized() -> None:
    text = "A\n\n\nB\n\nC"

    chunks = chunk_text(text, chunk_size=5, chunk_overlap=1)

    assert_chunk_invariants(text, chunks)
    assert_all_characters_covered(text, chunks)
    assert any("\n\n" in chunk.text for chunk in chunks)


@pytest.mark.parametrize("text", ["", "   \t\r\n"])
def test_empty_or_whitespace_only_text_returns_empty_list(text: str) -> None:
    assert chunk_text(text, chunk_size=10, chunk_overlap=0) == []


@pytest.mark.parametrize("value", [0, -1, 1.5, "10", True, None])
def test_invalid_chunk_size_is_rejected(value: object) -> None:
    with pytest.raises(InvalidChunkConfigurationError):
        chunk_text("content", chunk_size=value, chunk_overlap=0)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [-1, 10, 11, 1.5, "1", True, None])
def test_invalid_chunk_overlap_is_rejected(value: object) -> None:
    with pytest.raises(InvalidChunkConfigurationError):
        chunk_text("content", chunk_size=10, chunk_overlap=value)  # type: ignore[arg-type]


def test_non_string_and_boolean_inputs_are_rejected() -> None:
    with pytest.raises(InvalidTextError):
        chunk_text(True, chunk_size=10, chunk_overlap=0)  # type: ignore[arg-type]


def test_offsets_and_character_counts_are_exact() -> None:
    text = "one two three four five six seven"

    chunks = chunk_text(text, chunk_size=12, chunk_overlap=3)

    assert_chunk_invariants(text, chunks)
    assert_all_characters_covered(text, chunks)


def test_indices_start_at_zero_and_are_contiguous() -> None:
    chunks = chunk_text("x" * 50, chunk_size=12, chunk_overlap=2)

    assert [chunk.index for chunk in chunks] == list(range(len(chunks)))


def test_chunks_are_not_fully_duplicated() -> None:
    chunks = chunk_text("x" * 30, chunk_size=8, chunk_overlap=7)

    assert all(
        (current.start_char, current.end_char)
        != (previous.start_char, previous.end_char)
        for previous, current in zip(chunks, chunks[1:])
    )
    assert all(
        current.end_char > previous.end_char
        for previous, current in zip(chunks, chunks[1:])
    )


def test_large_overlap_terminates_and_covers_tail() -> None:
    text = "z" * 200

    chunks = chunk_text(text, chunk_size=20, chunk_overlap=19)

    assert len(chunks) == 181
    assert chunks[-1].end_char == len(text)


def test_single_page_pdf_has_page_one() -> None:
    result = extracted("PDF lesson", file_type="PDF", page_count=1)

    chunks = chunk_extracted_text(result, chunk_size=5, chunk_overlap=1)

    assert chunks
    assert {chunk.page_number for chunk in chunks} == {1}


def test_multiple_page_pdf_never_crosses_page_boundary() -> None:
    text = "First page\n\n\f\n\nSecond page"
    result = extracted(text, file_type="PDF", page_count=2)

    chunks = chunk_extracted_text(result, chunk_size=20, chunk_overlap=3)

    assert {chunk.page_number for chunk in chunks} == {1, 2}
    assert all("\f" not in chunk.text for chunk in chunks)
    assert all(
        text[chunk.start_char : chunk.end_char] == chunk.text for chunk in chunks
    )


def test_empty_pdf_page_preserves_later_page_number() -> None:
    text = "Page one\n\n\f\n\n\f\n\nPage three"
    result = extracted(text, file_type="PDF", page_count=3)

    chunks = chunk_extracted_text(result, chunk_size=20, chunk_overlap=2)

    assert {chunk.page_number for chunk in chunks} == {1, 3}
    assert not any(chunk.page_number == 2 for chunk in chunks)


def test_unreliable_pdf_boundaries_use_unknown_page_number() -> None:
    result = extracted("Page one without separators", file_type="PDF", page_count=2)

    chunks = chunk_extracted_text(result, chunk_size=10, chunk_overlap=2)

    assert chunks
    assert {chunk.page_number for chunk in chunks} == {None}


def test_docx_chunks_have_no_page_number() -> None:
    result = extracted("Reusable extracted content", file_type="DOCX")

    chunks = chunk_extracted_text(result, chunk_size=10, chunk_overlap=2)

    assert chunks
    assert {chunk.page_number for chunk in chunks} == {None}


def test_chunk_count_limit_is_enforced() -> None:
    text = "x" * (MAX_CHUNKS + 1)

    with pytest.raises(ChunkingLimitError):
        chunk_text(text, chunk_size=1, chunk_overlap=0)


def test_text_character_limit_is_enforced() -> None:
    with pytest.raises(ChunkingLimitError):
        chunk_text("x" * (MAX_TEXT_CHARACTERS + 1))


def test_oversized_chunk_configuration_is_rejected() -> None:
    with pytest.raises(InvalidChunkConfigurationError):
        chunk_text(
            "content",
            chunk_size=MAX_TEXT_CHARACTERS + 1,
            chunk_overlap=0,
        )


def test_chunk_extracted_text_accepts_real_extracted_text_shape() -> None:
    result = ExtractedText(
        text="StudyMate extracted lesson content",
        file_type="DOCX",
        character_count=34,
        page_count=None,
    )

    chunks = chunk_extracted_text(result, chunk_size=14, chunk_overlap=3)

    assert chunks
    assert_chunk_invariants(result.text, chunks)
    assert_all_characters_covered(result.text, chunks)


def test_chunk_extracted_text_rejects_unrelated_objects() -> None:
    with pytest.raises(InvalidTextError):
        chunk_extracted_text(object())  # type: ignore[arg-type]
