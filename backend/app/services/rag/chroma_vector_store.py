"""ChromaDB storage for externally generated document-chunk embeddings."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import isfinite
from typing import Any

import chromadb

from app.core.config import Settings


DISTANCE_METRIC = "cosine"
COLLECTION_SCHEMA_VERSION = 1
MAX_QUERY_LIMIT = 100
_REQUIRED_METADATA_KEYS = frozenset(
    {"user_id", "document_id", "chunk_id", "chunk_index"}
)
_ALLOWED_METADATA_KEYS = _REQUIRED_METADATA_KEYS | {"page_number"}


class ChromaVectorStoreError(Exception):
    """Base error for safe vector-store failures."""


class InvalidVectorRecordError(ChromaVectorStoreError, ValueError):
    """Raised when a chunk record is invalid before persistence."""


class InvalidVectorQueryError(ChromaVectorStoreError, ValueError):
    """Raised when a vector query is invalid before execution."""


class IncompatibleChromaCollectionError(ChromaVectorStoreError):
    """Raised when an existing collection has unsafe configuration."""


class ChromaOperationError(ChromaVectorStoreError):
    """Raised when ChromaDB cannot complete or validate an operation."""


class ChromaOpenError(ChromaOperationError):
    """Raised when the persistent client or collection cannot be opened."""


@dataclass(frozen=True, slots=True)
class ChunkVectorRecord:
    """One precomputed chunk embedding and its safe retrieval metadata."""

    id: str
    embedding: Sequence[float]
    content: str
    metadata: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class ChunkQueryResult:
    """One validated nearest-neighbor result returned by ChromaDB."""

    id: str
    content: str
    metadata: Mapping[str, int]
    distance: float


class ChromaVectorStore:
    """Persistent, owner-filtered storage for precomputed chunk vectors."""

    def __init__(
        self,
        settings: Settings,
        *,
        client: Any | None = None,
        create_if_missing: bool = True,
    ) -> None:
        if settings.gemini_embedding_dimensions <= 0:
            raise ValueError("Embedding dimensions must be positive.")
        if not isinstance(create_if_missing, bool):
            raise ValueError("create_if_missing must be a boolean.")

        self._dimensions = settings.gemini_embedding_dimensions
        self._collection_name = settings.chroma_collection_name
        try:
            self._client = (
                client
                if client is not None
                else chromadb.PersistentClient(
                    path=settings.chroma_persist_directory
                )
            )
            if create_if_missing:
                self._collection = self._client.get_or_create_collection(
                    name=self._collection_name,
                    configuration={"hnsw": {"space": DISTANCE_METRIC}},
                    metadata={
                        "embedding_dimensions": self._dimensions,
                        "distance_metric": DISTANCE_METRIC,
                        "schema_version": COLLECTION_SCHEMA_VERSION,
                    },
                    embedding_function=None,
                )
            else:
                self._collection = self._client.get_collection(
                    name=self._collection_name,
                    embedding_function=None,
                )
            self._validate_collection_compatibility()
        except IncompatibleChromaCollectionError:
            raise
        except Exception as exc:
            raise ChromaOpenError(
                "The ChromaDB collection could not be opened."
            ) from exc

    def upsert_chunks(self, records: Sequence[ChunkVectorRecord]) -> int:
        """Idempotently persist validated, precomputed chunk vectors."""

        record_values = tuple(records)
        if not record_values:
            raise InvalidVectorRecordError(
                "At least one vector record is required."
            )

        ids: list[str] = []
        embeddings: list[list[float]] = []
        documents: list[str] = []
        metadatas: list[dict[str, int]] = []
        for record in record_values:
            vector, metadata = self._validate_record(record)
            ids.append(record.id)
            embeddings.append(vector)
            documents.append(record.content)
            metadatas.append(metadata)

        if len(set(ids)) != len(ids):
            raise InvalidVectorRecordError(
                "Vector record IDs must be unique within one request."
            )

        try:
            self._collection.upsert(
                ids=ids,
                embeddings=embeddings,
                documents=documents,
                metadatas=metadatas,
            )
        except Exception as exc:
            raise ChromaOperationError(
                "Chunk vectors could not be upserted."
            ) from exc
        return len(record_values)

    def query_chunks(
        self,
        query_embedding: Sequence[float],
        *,
        user_id: int,
        document_id: int,
        limit: int,
    ) -> list[ChunkQueryResult]:
        """Query vectors with mandatory owner and document filters."""

        self._validate_positive_identifier(
            user_id,
            "user_id",
            InvalidVectorQueryError,
        )
        self._validate_positive_identifier(
            document_id,
            "document_id",
            InvalidVectorQueryError,
        )
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise InvalidVectorQueryError("Query limit must be an integer.")
        if limit < 1 or limit > MAX_QUERY_LIMIT:
            raise InvalidVectorQueryError(
                f"Query limit must be between 1 and {MAX_QUERY_LIMIT}."
            )
        vector = self._validate_embedding(
            query_embedding,
            InvalidVectorQueryError,
        )

        try:
            response = self._collection.query(
                query_embeddings=[vector],
                n_results=limit,
                where={
                    "$and": [
                        {"user_id": {"$eq": user_id}},
                        {"document_id": {"$eq": document_id}},
                    ]
                },
                include=["documents", "metadatas", "distances"],
            )
        except Exception as exc:
            raise ChromaOperationError(
                "Chunk vectors could not be queried."
            ) from exc
        return self._validate_query_response(
            response,
            expected_user_id=user_id,
            expected_document_id=document_id,
        )

    def delete_document_vectors(self, *, user_id: int, document_id: int) -> None:
        """Idempotently delete vectors scoped to one owned document."""

        self._validate_positive_identifier(
            user_id,
            "user_id",
            InvalidVectorQueryError,
        )
        self._validate_positive_identifier(
            document_id,
            "document_id",
            InvalidVectorQueryError,
        )
        try:
            self._collection.delete(
                where={
                    "$and": [
                        {"user_id": {"$eq": user_id}},
                        {"document_id": {"$eq": document_id}},
                    ]
                }
            )
        except Exception as exc:
            raise ChromaOperationError(
                "Document vectors could not be deleted."
            ) from exc

    def get_document_vector_ids(
        self,
        *,
        user_id: int,
        document_id: int,
    ) -> set[str]:
        """Return exact vector IDs scoped to one user and document."""

        self._validate_positive_identifier(
            user_id,
            "user_id",
            InvalidVectorQueryError,
        )
        self._validate_positive_identifier(
            document_id,
            "document_id",
            InvalidVectorQueryError,
        )
        try:
            response = self._collection.get(
                where={
                    "$and": [
                        {"user_id": {"$eq": user_id}},
                        {"document_id": {"$eq": document_id}},
                    ]
                },
                include=[],
            )
        except Exception as exc:
            raise ChromaOperationError(
                "Document vector IDs could not be queried."
            ) from exc
        if not isinstance(response, Mapping):
            raise ChromaOperationError("ChromaDB returned an invalid response.")
        ids = response.get("ids")
        if (
            not isinstance(ids, list)
            or any(not isinstance(vector_id, str) for vector_id in ids)
            or len(ids) != len(set(ids))
        ):
            raise ChromaOperationError("ChromaDB returned invalid vector IDs.")
        return set(ids)

    def close(self) -> None:
        """Release this client's local ChromaDB resources when supported."""

        close = getattr(self._client, "close", None)
        if callable(close):
            close()

    def _validate_collection_compatibility(self) -> None:
        metadata = self._collection.metadata
        schema = self._collection.schema
        embedding_key = getattr(schema, "keys", {}).get("#embedding")
        float_list = getattr(embedding_key, "float_list", None)
        vector_index = getattr(float_list, "vector_index", None)
        vector_configuration = getattr(vector_index, "config", None)
        metric = getattr(vector_configuration, "space", None)
        embedding_function = getattr(
            vector_configuration,
            "embedding_function",
            object(),
        )
        if (
            not isinstance(metadata, Mapping)
            or metadata.get("embedding_dimensions") != self._dimensions
            or metadata.get("distance_metric") != DISTANCE_METRIC
            or metadata.get("schema_version") != COLLECTION_SCHEMA_VERSION
            or metric != DISTANCE_METRIC
            or embedding_function is not None
        ):
            raise IncompatibleChromaCollectionError(
                "The existing ChromaDB collection is incompatible."
            )

    def _validate_record(
        self,
        record: ChunkVectorRecord,
    ) -> tuple[list[float], dict[str, int]]:
        if not isinstance(record, ChunkVectorRecord):
            raise InvalidVectorRecordError("Vector record is invalid.")
        if not isinstance(record.content, str) or not record.content.strip():
            raise InvalidVectorRecordError("Chunk content must not be empty.")
        if not isinstance(record.metadata, Mapping):
            raise InvalidVectorRecordError("Chunk metadata is invalid.")

        keys = set(record.metadata)
        if not _REQUIRED_METADATA_KEYS.issubset(keys) or not keys.issubset(
            _ALLOWED_METADATA_KEYS
        ):
            raise InvalidVectorRecordError(
                "Chunk metadata contains missing or unsupported fields."
            )
        metadata = dict(record.metadata)
        self._validate_positive_identifier(metadata["user_id"], "user_id")
        self._validate_positive_identifier(
            metadata["document_id"],
            "document_id",
        )
        self._validate_positive_identifier(metadata["chunk_id"], "chunk_id")
        chunk_index = metadata["chunk_index"]
        if (
            isinstance(chunk_index, bool)
            or not isinstance(chunk_index, int)
            or chunk_index < 0
        ):
            raise InvalidVectorRecordError(
                "chunk_index must be a nonnegative integer."
            )
        page_number = metadata.get("page_number")
        if page_number is not None:
            self._validate_positive_identifier(page_number, "page_number")
        expected_id = f"document_chunk:{metadata['chunk_id']}"
        if record.id != expected_id:
            raise InvalidVectorRecordError(
                "Vector record ID does not match its chunk ID."
            )
        return (
            self._validate_embedding(
                record.embedding,
                InvalidVectorRecordError,
            ),
            metadata,
        )

    def _validate_embedding(
        self,
        embedding: Sequence[float],
        error_type: type[InvalidVectorRecordError]
        | type[InvalidVectorQueryError],
    ) -> list[float]:
        if isinstance(embedding, (str, bytes)):
            raise error_type("Embedding must be a numeric sequence.")
        try:
            values = list(embedding)
        except TypeError as exc:
            raise error_type("Embedding must be a numeric sequence.") from exc
        if len(values) != self._dimensions:
            raise error_type(
                f"Embedding must contain exactly {self._dimensions} values."
            )
        normalized: list[float] = []
        for value in values:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise error_type("Embedding values must be finite numbers.")
            normalized_value = float(value)
            if not isfinite(normalized_value):
                raise error_type("Embedding values must be finite numbers.")
            normalized.append(normalized_value)
        return normalized

    def _validate_query_response(
        self,
        response: object,
        *,
        expected_user_id: int,
        expected_document_id: int,
    ) -> list[ChunkQueryResult]:
        if not isinstance(response, Mapping):
            raise ChromaOperationError("ChromaDB returned an invalid response.")
        try:
            ids = response["ids"][0]
            documents = response["documents"][0]
            metadatas = response["metadatas"][0]
            distances = response["distances"][0]
        except (KeyError, IndexError, TypeError):
            raise ChromaOperationError(
                "ChromaDB returned an invalid response."
            ) from None
        if not all(
            isinstance(values, list)
            for values in (ids, documents, metadatas, distances)
        ) or len({len(ids), len(documents), len(metadatas), len(distances)}) != 1:
            raise ChromaOperationError("ChromaDB returned an invalid response.")

        results: list[ChunkQueryResult] = []
        for vector_id, content, metadata, distance in zip(
            ids,
            documents,
            metadatas,
            distances,
            strict=True,
        ):
            if (
                not isinstance(vector_id, str)
                or not isinstance(content, str)
                or not isinstance(metadata, Mapping)
                or metadata.get("user_id") != expected_user_id
                or metadata.get("document_id") != expected_document_id
                or isinstance(distance, bool)
                or not isinstance(distance, (int, float))
                or not isfinite(float(distance))
            ):
                raise ChromaOperationError(
                    "ChromaDB returned an invalid response."
                )
            safe_metadata = {
                key: value
                for key, value in metadata.items()
                if key in _ALLOWED_METADATA_KEYS
            }
            metadata_keys = set(safe_metadata)
            if (
                metadata_keys != set(metadata)
                or not _REQUIRED_METADATA_KEYS.issubset(metadata_keys)
                or safe_metadata.get("chunk_id") is None
                or vector_id
                != f"document_chunk:{safe_metadata['chunk_id']}"
            ):
                raise ChromaOperationError(
                    "ChromaDB returned unsupported metadata."
                )
            self._validate_result_metadata(safe_metadata)
            results.append(
                ChunkQueryResult(
                    id=vector_id,
                    content=content,
                    metadata=safe_metadata,
                    distance=float(distance),
                )
            )
        return results

    @staticmethod
    def _validate_positive_identifier(
        value: object,
        name: str,
        error_type: type[ChromaVectorStoreError] = InvalidVectorRecordError,
    ) -> None:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise error_type(f"{name} must be a positive integer.")

    @staticmethod
    def _validate_result_metadata(metadata: Mapping[str, object]) -> None:
        positive_fields = ("user_id", "document_id", "chunk_id")
        if any(
            isinstance(metadata.get(field), bool)
            or not isinstance(metadata.get(field), int)
            or metadata[field] <= 0
            for field in positive_fields
        ):
            raise ChromaOperationError("ChromaDB returned invalid metadata.")
        chunk_index = metadata.get("chunk_index")
        if (
            isinstance(chunk_index, bool)
            or not isinstance(chunk_index, int)
            or chunk_index < 0
        ):
            raise ChromaOperationError("ChromaDB returned invalid metadata.")
        page_number = metadata.get("page_number")
        if page_number is not None and (
            isinstance(page_number, bool)
            or not isinstance(page_number, int)
            or page_number <= 0
        ):
            raise ChromaOperationError("ChromaDB returned invalid metadata.")
