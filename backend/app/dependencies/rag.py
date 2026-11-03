"""Lazy request-scoped dependencies for RAG indexing."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from time import monotonic
from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.services.rag.chroma_vector_store import (
    ChromaVectorStore,
    ChunkQueryResult,
    ChunkVectorRecord,
)
from app.services.rag.answer_service import (
    AnswerProvider,
    GeneratedAnswer,
    GeminiAnswerService,
)
from app.services.rag.chat_service import RetrievalService
from app.services.rag.document_retrieval import (
    DocumentRetrievalVectorStore,
    RetrievedDocumentChunk,
    retrieve_document_chunks,
)
from app.services.rag.document_indexing import (
    DocumentVectorStore,
    EmbeddingRetryPolicy,
)
import threading

from app.services.rag.embedding_service import (
    DEFAULT_FASTEMBED_MODEL,
    EmbeddingProvider,
    FastEmbedProvider,
    GeminiEmbeddingService,
)
from app.services.summary.concurrency import (
    CapacityConcurrencyCoordinator,
    SummaryConcurrencyLimits,
    get_capacity_concurrency_coordinator,
)


@dataclass(frozen=True, slots=True)
class RagIndexingResources:
    """External services used by one synchronous indexing request."""

    embedder: EmbeddingProvider
    vector_store: DocumentVectorStore
    concurrency_limits: SummaryConcurrencyLimits = SummaryConcurrencyLimits()
    concurrency_coordinator: CapacityConcurrencyCoordinator | None = None
    embedding_batch_size: int = 16
    batch_delay_seconds: float = 1.5
    retry_policy: EmbeddingRetryPolicy = EmbeddingRetryPolicy(5, 5.0, 60.0, 300.0)
    indexing_lease_seconds: int = 900


@dataclass(frozen=True, slots=True)
class RagChatResources:
    """Lazy external operations used by one synchronous chat request."""

    retrieval_service: RetrievalService
    answer_provider: AnswerProvider
    concurrency_limits: SummaryConcurrencyLimits = SummaryConcurrencyLimits()
    concurrency_coordinator: CapacityConcurrencyCoordinator | None = None
    deadline_seconds: float = 60.0
    clock: Callable[[], float] = monotonic


@dataclass(frozen=True, slots=True)
class DocumentDeletionResources:
    """Lazy ChromaDB dependency for a synchronous deletion request."""

    vector_store: _LazyChromaVectorStore


class _LazyGeminiEmbeddingProvider:
    """Delay Gemini service construction until the claimed document is embedded."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._service: GeminiEmbeddingService | None = None

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._get_service().embed_documents(texts)

    def embed_query(
        self,
        query: str,
        *,
        timeout_seconds: float | None = None,
    ) -> list[float]:
        return self._get_service().embed_query(
            query,
            timeout_seconds=timeout_seconds,
        )

    def close(self) -> None:
        if self._service is not None:
            self._service.close()

    def _get_service(self) -> GeminiEmbeddingService:
        if self._service is None:
            self._service = GeminiEmbeddingService(self._settings)
        return self._service


_fastembed_singleton: FastEmbedProvider | None = None
_fastembed_lock = threading.Lock()


def get_fastembed_provider(
    model_name: str = DEFAULT_FASTEMBED_MODEL,
    cache_dir: str | None = None,
) -> FastEmbedProvider:
    """Return a thread-safe cached FastEmbedProvider singleton."""
    global _fastembed_singleton
    if _fastembed_singleton is None or _fastembed_singleton._model_name != model_name:
        with _fastembed_lock:
            if _fastembed_singleton is None or _fastembed_singleton._model_name != model_name:
                _fastembed_singleton = FastEmbedProvider(
                    model_name=model_name,
                    cache_dir=cache_dir,
                )
    return _fastembed_singleton


class _LazyChromaVectorStore:
    """Delay opening ChromaDB until a claimed document has vectors to persist."""

    def __init__(
        self,
        settings: Settings,
        *,
        create_if_missing: bool = True,
        dimensions: int | None = None,
        collection_name: str | None = None,
        auto_recreate_on_mismatch: bool = False,
    ) -> None:
        self._settings = settings
        self._create_if_missing = create_if_missing
        self._dimensions = dimensions
        self._collection_name = collection_name
        self._auto_recreate_on_mismatch = auto_recreate_on_mismatch
        self._store: ChromaVectorStore | None = None

    def upsert_chunks(self, records: Sequence[ChunkVectorRecord]) -> int:
        return self._get_store().upsert_chunks(records)

    def get_document_vector_ids(
        self,
        *,
        user_id: int,
        document_id: int,
    ) -> set[str]:
        return self._get_store().get_document_vector_ids(
            user_id=user_id,
            document_id=document_id,
        )

    def delete_document_vectors(
        self,
        *,
        user_id: int,
        document_id: int,
    ) -> None:
        self._get_store().delete_document_vectors(
            user_id=user_id,
            document_id=document_id,
        )

    def query_chunks(
        self,
        query_embedding: Sequence[float],
        *,
        user_id: int,
        document_id: int,
        limit: int,
    ) -> list[ChunkQueryResult]:
        return self._get_store().query_chunks(
            query_embedding,
            user_id=user_id,
            document_id=document_id,
            limit=limit,
        )

    def close(self) -> None:
        if self._store is not None:
            self._store.close()
            self._store = None

    def _get_store(self) -> ChromaVectorStore:
        if self._store is None:
            dimensions = (
                self._dimensions
                if self._dimensions is not None
                else (
                    self._settings.fastembed_dimensions
                    if getattr(self._settings, "embedding_provider", "fastembed") == "fastembed"
                    else self._settings.gemini_embedding_dimensions
                )
            )
            collection_name = (
                self._collection_name
                if self._collection_name is not None
                else (
                    self._settings.fastembed_collection_name
                    if getattr(self._settings, "embedding_provider", "fastembed") == "fastembed"
                    else self._settings.chroma_collection_name
                )
            )
            self._store = ChromaVectorStore(
                self._settings,
                create_if_missing=self._create_if_missing,
                dimensions=dimensions,
                collection_name=collection_name,
                auto_recreate_on_mismatch=self._auto_recreate_on_mismatch,
            )
        return self._store


class _LazyGeminiAnswerProvider:
    """Delay answer service and SDK client creation until generation."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._service: GeminiAnswerService | None = None

    def generate_answer(
        self,
        question: str,
        retrieved_chunks: Sequence[RetrievedDocumentChunk],
        *,
        timeout_seconds: float | None = None,
    ) -> GeneratedAnswer:
        return self._get_service().generate_answer(
            question,
            retrieved_chunks,
            timeout_seconds=timeout_seconds,
        )

    def close(self) -> None:
        if self._service is not None:
            self._service.close()

    def _get_service(self) -> GeminiAnswerService:
        if self._service is None:
            self._service = GeminiAnswerService(self._settings)
        return self._service


class _DocumentRetrievalOperation:
    """Bind lazy embedding and vector providers to retrieval's interface."""

    def __init__(
        self,
        embedder: EmbeddingProvider,
        vector_store: DocumentRetrievalVectorStore,
        *,
        max_cosine_distance: float | None = None,
    ) -> None:
        self._embedder = embedder
        self._vector_store = vector_store
        self._max_cosine_distance = max_cosine_distance

    def __call__(
        self,
        db: Session,
        *,
        document_id: int,
        user_id: int,
        query: str,
        deadline=None,
    ) -> list[RetrievedDocumentChunk]:
        return retrieve_document_chunks(
            db,
            self._embedder,
            self._vector_store,
            document_id=document_id,
            user_id=user_id,
            query=query,
            max_cosine_distance=self._max_cosine_distance,
            deadline=deadline,
        )


def get_rag_indexing_resources(
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[Session, Depends(get_db)],
) -> Iterator[RagIndexingResources]:
    """Create external clients lazily and release request-owned resources."""

    if not settings.gemini_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Dịch vụ lập chỉ mục RAG chưa được cấu hình.",
        )

    is_local = getattr(settings, "embedding_provider", "fastembed") == "fastembed" 

    if is_local:
        embedder: EmbeddingProvider = get_fastembed_provider(
            model_name=settings.fastembed_model
        )
        vector_store = _LazyChromaVectorStore(
            settings,
            create_if_missing=True,
            dimensions=settings.fastembed_dimensions,
            collection_name=settings.fastembed_collection_name,
            auto_recreate_on_mismatch=True,
        )
        batch_delay = 0.0
        retry_policy = EmbeddingRetryPolicy(
            max_retries=0,
            base_delay_seconds=0.1,
            max_delay_seconds=0.1,
            max_total_wait_seconds=0.1,
        )
        batch_size = 32
    else:
        embedder = _LazyGeminiEmbeddingProvider(settings)
        vector_store = _LazyChromaVectorStore(
            settings,
            create_if_missing=True,
            dimensions=settings.gemini_embedding_dimensions,
            collection_name=settings.chroma_collection_name,
            auto_recreate_on_mismatch=False,
        )
        batch_delay = settings.gemini_embedding_batch_delay_seconds
        retry_policy = EmbeddingRetryPolicy(
            max_retries=settings.gemini_embedding_max_retries,
            base_delay_seconds=settings.gemini_embedding_retry_base_seconds,
            max_delay_seconds=settings.gemini_embedding_retry_max_seconds,
            max_total_wait_seconds=settings.gemini_embedding_retry_max_wait_seconds,
        )
        batch_size = settings.gemini_embedding_batch_size

    concurrency_limits = SummaryConcurrencyLimits(
        global_limit=settings.indexing_global_concurrency,
        per_user_limit=settings.indexing_user_concurrency,
    )

    try:
        yield RagIndexingResources(
            embedder=embedder,
            vector_store=vector_store,
            concurrency_limits=concurrency_limits,
            concurrency_coordinator=get_capacity_concurrency_coordinator(
                db,
                namespace="document_indexing",
                limits=concurrency_limits,
            ),
            embedding_batch_size=batch_size,
            batch_delay_seconds=batch_delay,
            retry_policy=retry_policy,
            indexing_lease_seconds=settings.document_indexing_lease_seconds,
        )
    finally:
        _close_safely(vector_store)
        _close_safely(embedder)


def get_rag_chat_resources(
    settings: Annotated[Settings, Depends(get_settings)],
) -> Iterator[RagChatResources]:
    """Provide lazy request-owned retrieval and answer dependencies."""

    if not settings.gemini_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Dịch vụ hỏi đáp AI chưa được cấu hình.",
        )

    is_local = getattr(settings, "embedding_provider", "fastembed") == "fastembed"
    if is_local:
        embedder: EmbeddingProvider = get_fastembed_provider(
            model_name=settings.fastembed_model
        )
        vector_store = _LazyChromaVectorStore(
            settings,
            create_if_missing=False,
            dimensions=settings.fastembed_dimensions,
            collection_name=settings.fastembed_collection_name,
            auto_recreate_on_mismatch=True,
        )
    else:
        embedder = _LazyGeminiEmbeddingProvider(settings)
        vector_store = _LazyChromaVectorStore(
            settings,
            create_if_missing=False,
            dimensions=settings.gemini_embedding_dimensions,
            collection_name=settings.chroma_collection_name,
            auto_recreate_on_mismatch=False,
        )
    answer_provider = _LazyGeminiAnswerProvider(settings)
    try:
        yield RagChatResources(
            retrieval_service=_DocumentRetrievalOperation(
                embedder,
                vector_store,
                max_cosine_distance=settings.rag_max_cosine_distance,
            ),
            answer_provider=answer_provider,
            concurrency_limits=SummaryConcurrencyLimits(
                global_limit=settings.chat_global_concurrency,
                per_user_limit=settings.chat_user_concurrency,
            ),
            deadline_seconds=settings.chat_deadline_seconds,
        )
    finally:
        _close_safely(answer_provider)
        _close_safely(vector_store)
        _close_safely(embedder)


def get_document_deletion_resources(
    settings: Annotated[Settings, Depends(get_settings)],
) -> Iterator[DocumentDeletionResources]:
    """Open ChromaDB lazily without constructing a Gemini client."""

    vector_store = _LazyChromaVectorStore(settings)
    try:
        yield DocumentDeletionResources(vector_store=vector_store)
    finally:
        _close_safely(vector_store)


def _close_safely(resource: object) -> None:
    """Best-effort request cleanup that never exposes provider exceptions."""

    try:
        close = getattr(resource, "close", None)
        if callable(close):
            close()
    except Exception:
        pass
