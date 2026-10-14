"""Isolated tests for ChromaDB configuration and vector persistence."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import chromadb
import pytest

from app.core.config import (
    BACKEND_DIR,
    DEFAULT_CHROMA_COLLECTION_NAME,
    _load_chroma_collection_name,
    _load_chroma_persist_directory,
    _load_gemini_embedding_dimensions,
    get_settings,
)
from app.services.rag.chroma_vector_store import (
    ChromaOpenError,
    ChromaVectorStore,
    ChunkVectorRecord,
    IncompatibleChromaCollectionError,
    InvalidVectorQueryError,
    InvalidVectorRecordError,
)


DIMENSIONS = 768
COLLECTION_NAME = "test_document_chunks_gemini2_768_v1"


def fake_embedding(index: int = 0) -> list[float]:
    values = [0.0] * DIMENSIONS
    values[index] = 1.0
    return values


def make_record(
    chunk_id: int,
    *,
    user_id: int = 1,
    document_id: int = 10,
    chunk_index: int = 0,
    content: str = "Nội dung học tập tiếng Việt.",
    page_number: int | None = None,
    embedding_index: int = 0,
) -> ChunkVectorRecord:
    metadata = {
        "user_id": user_id,
        "document_id": document_id,
        "chunk_id": chunk_id,
        "chunk_index": chunk_index,
    }
    if page_number is not None:
        metadata["page_number"] = page_number
    return ChunkVectorRecord(
        id=f"document_chunk:{chunk_id}",
        embedding=fake_embedding(embedding_index),
        content=content,
        metadata=metadata,
    )


def make_settings(path: Path, *, collection_name: str = COLLECTION_NAME):
    return replace(
        get_settings(),
        chroma_persist_directory=path,
        chroma_collection_name=collection_name,
        gemini_embedding_dimensions=DIMENSIONS,
    )


@pytest.fixture
def vector_store(tmp_path: Path):
    client = chromadb.PersistentClient(path=tmp_path / "chroma")
    store = ChromaVectorStore(
        make_settings(tmp_path / "chroma"),
        client=client,
    )
    yield store
    store.close()
    client.clear_system_cache()


def test_chroma_config_defaults_are_backend_relative_and_valid(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("CHROMA_PERSIST_DIRECTORY", raising=False)
    monkeypatch.delenv("CHROMA_COLLECTION_NAME", raising=False)
    monkeypatch.delenv("GEMINI_EMBEDDING_DIMENSIONS", raising=False)
    monkeypatch.chdir(tmp_path)

    assert _load_chroma_persist_directory() == (
        BACKEND_DIR / "storage" / "chroma"
    ).resolve(strict=False)
    assert _load_chroma_collection_name() == DEFAULT_CHROMA_COLLECTION_NAME
    assert _load_gemini_embedding_dimensions() == DIMENSIONS


@pytest.mark.parametrize("value", ["0", "-1", "not-an-integer"])
def test_chroma_config_rejects_invalid_embedding_dimensions(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv("GEMINI_EMBEDDING_DIMENSIONS", value)

    with pytest.raises(RuntimeError):
        _load_gemini_embedding_dimensions()


def test_relative_chroma_path_is_resolved_from_backend(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("CHROMA_PERSIST_DIRECTORY", "runtime/chroma")
    monkeypatch.chdir(tmp_path)

    assert _load_chroma_persist_directory() == (
        BACKEND_DIR / "runtime" / "chroma"
    ).resolve(strict=False)


def test_upsert_one_chunk_successfully(vector_store: ChromaVectorStore) -> None:
    assert vector_store.upsert_chunks([make_record(1, page_number=2)]) == 1

    results = vector_store.query_chunks(
        fake_embedding(),
        user_id=1,
        document_id=10,
        limit=5,
    )

    assert len(results) == 1
    assert results[0].id == "document_chunk:1"
    assert results[0].metadata == {
        "user_id": 1,
        "document_id": 10,
        "chunk_id": 1,
        "chunk_index": 0,
        "page_number": 2,
    }


def test_repeated_upsert_does_not_create_duplicate(
    vector_store: ChromaVectorStore,
) -> None:
    vector_store.upsert_chunks([make_record(1, content="Phiên bản đầu")])
    vector_store.upsert_chunks([make_record(1, content="Phiên bản mới")])

    results = vector_store.query_chunks(
        fake_embedding(),
        user_id=1,
        document_id=10,
        limit=5,
    )

    assert len(results) == 1
    assert results[0].content == "Phiên bản mới"


def test_query_returns_nearest_matching_chunk(
    vector_store: ChromaVectorStore,
) -> None:
    vector_store.upsert_chunks(
        [
            make_record(1, embedding_index=0, content="Khớp"),
            make_record(
                2,
                chunk_index=1,
                embedding_index=1,
                content="Không khớp bằng",
            ),
        ]
    )

    results = vector_store.query_chunks(
        fake_embedding(0),
        user_id=1,
        document_id=10,
        limit=1,
    )

    assert [result.id for result in results] == ["document_chunk:1"]
    assert results[0].distance == pytest.approx(0.0)


def test_query_never_returns_another_users_chunks(
    vector_store: ChromaVectorStore,
) -> None:
    vector_store.upsert_chunks(
        [
            make_record(1, user_id=1),
            make_record(2, user_id=2),
        ]
    )

    results = vector_store.query_chunks(
        fake_embedding(),
        user_id=1,
        document_id=10,
        limit=10,
    )

    assert [result.metadata["user_id"] for result in results] == [1]


def test_query_never_returns_another_documents_chunks(
    vector_store: ChromaVectorStore,
) -> None:
    vector_store.upsert_chunks(
        [
            make_record(1, document_id=10),
            make_record(2, document_id=20),
        ]
    )

    results = vector_store.query_chunks(
        fake_embedding(),
        user_id=1,
        document_id=10,
        limit=10,
    )

    assert [result.metadata["document_id"] for result in results] == [10]


def test_delete_only_removes_selected_document_and_is_idempotent(
    vector_store: ChromaVectorStore,
) -> None:
    vector_store.upsert_chunks(
        [
            make_record(1, document_id=10),
            make_record(2, document_id=20),
            make_record(3, user_id=2, document_id=10),
        ]
    )

    vector_store.delete_document_vectors(user_id=1, document_id=10)
    vector_store.delete_document_vectors(user_id=1, document_id=10)

    assert vector_store.query_chunks(
        fake_embedding(), user_id=1, document_id=10, limit=10
    ) == []
    assert len(
        vector_store.query_chunks(
            fake_embedding(), user_id=1, document_id=20, limit=10
        )
    ) == 1


def test_get_document_vector_ids_is_exactly_owner_scoped(
    vector_store: ChromaVectorStore,
) -> None:
    vector_store.upsert_chunks(
        [
            make_record(1, user_id=1, document_id=10),
            make_record(2, user_id=1, document_id=20),
            make_record(3, user_id=2, document_id=10),
        ]
    )

    assert vector_store.get_document_vector_ids(
        user_id=1,
        document_id=10,
    ) == {"document_chunk:1"}
    assert len(
        vector_store.query_chunks(
            fake_embedding(), user_id=2, document_id=10, limit=10
        )
    ) == 1


def test_wrong_embedding_dimension_is_rejected(
    vector_store: ChromaVectorStore,
) -> None:
    invalid_record = replace(make_record(1), embedding=[0.0] * 767)

    with pytest.raises(InvalidVectorRecordError):
        vector_store.upsert_chunks([invalid_record])
    with pytest.raises(InvalidVectorQueryError):
        vector_store.query_chunks(
            [0.0] * 769,
            user_id=1,
            document_id=10,
            limit=5,
        )


@pytest.mark.parametrize("limit", [0, -1, 101, 1.5, True])
def test_invalid_query_limit_is_rejected(
    vector_store: ChromaVectorStore,
    limit: object,
) -> None:
    with pytest.raises(InvalidVectorQueryError):
        vector_store.query_chunks(
            fake_embedding(),
            user_id=1,
            document_id=10,
            limit=limit,
        )


def test_vectors_persist_when_a_new_client_uses_the_same_directory(
    tmp_path: Path,
) -> None:
    persist_directory = tmp_path / "persistent-chroma"
    first_client = chromadb.PersistentClient(path=persist_directory)
    first_store = ChromaVectorStore(
        make_settings(persist_directory),
        client=first_client,
    )
    first_store.upsert_chunks([make_record(1)])
    first_store.close()
    first_client.clear_system_cache()

    second_client = chromadb.PersistentClient(path=persist_directory)
    second_store = ChromaVectorStore(
        make_settings(persist_directory),
        client=second_client,
    )
    try:
        results = second_store.query_chunks(
            fake_embedding(),
            user_id=1,
            document_id=10,
            limit=5,
        )
        assert [result.id for result in results] == ["document_chunk:1"]
    finally:
        second_store.close()
        second_client.clear_system_cache()


@pytest.mark.parametrize(
    ("dimensions", "metric"),
    [(384, "cosine"), (DIMENSIONS, "l2")],
    ids=("wrong-dimension", "wrong-distance-metric"),
)
def test_incompatible_existing_collection_is_rejected(
    tmp_path: Path,
    dimensions: int,
    metric: str,
) -> None:
    persist_directory = tmp_path / f"incompatible-{dimensions}-{metric}"
    client = chromadb.PersistentClient(path=persist_directory)
    client.create_collection(
        COLLECTION_NAME,
        configuration={"hnsw": {"space": metric}},
        metadata={
            "embedding_dimensions": dimensions,
            "distance_metric": metric,
            "schema_version": 1,
        },
        embedding_function=None,
    )
    try:
        with pytest.raises(IncompatibleChromaCollectionError):
            ChromaVectorStore(
                make_settings(persist_directory),
                client=client,
            )
    finally:
        client.close()
        client.clear_system_cache()


def test_collection_open_failure_has_a_safe_specific_type(tmp_path: Path) -> None:
    class FailingClient:
        def get_or_create_collection(self, **kwargs: object) -> object:
            raise RuntimeError("private internal path and database detail")

    with pytest.raises(ChromaOpenError) as captured:
        ChromaVectorStore(
            make_settings(tmp_path / "unused"),
            client=FailingClient(),
        )

    assert "private" not in str(captured.value)


def test_read_only_open_does_not_create_a_missing_collection(
    tmp_path: Path,
) -> None:
    class MissingCollectionClient:
        def __init__(self) -> None:
            self.get_calls = 0
            self.create_calls = 0

        def get_collection(self, **kwargs: object) -> object:
            self.get_calls += 1
            raise RuntimeError("collection is missing")

        def get_or_create_collection(self, **kwargs: object) -> object:
            self.create_calls += 1
            raise AssertionError("read-only open must not create a collection")

    client = MissingCollectionClient()

    with pytest.raises(ChromaOpenError):
        ChromaVectorStore(
            make_settings(tmp_path / "unused"),
            client=client,
            create_if_missing=False,
        )

    assert client.get_calls == 1
    assert client.create_calls == 0


def test_sensitive_or_unknown_metadata_is_rejected(
    vector_store: ChromaVectorStore,
) -> None:
    record = make_record(1)
    invalid_record = replace(
        record,
        metadata={**record.metadata, "storage_key": "must-not-be-stored"},
    )

    with pytest.raises(InvalidVectorRecordError):
        vector_store.upsert_chunks([invalid_record])
