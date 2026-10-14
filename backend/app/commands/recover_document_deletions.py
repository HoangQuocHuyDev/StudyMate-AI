"""Run one opt-in document-deletion recovery sweep.

Invoke separately from Uvicorn only after setting
DOCUMENT_DELETION_RECOVERY_ENABLED=true for the intended environment.
"""

from __future__ import annotations

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.services.document_deletion import recover_document_deletions
from app.services.file_storage import FileStorage
from app.services.rag.chroma_vector_store import ChromaVectorStore


def run() -> int:
    """Run one bounded sweep; return a process-friendly status code."""

    settings = get_settings()
    if not settings.document_deletion_recovery_enabled:
        return 2

    storage = FileStorage.from_settings()
    vector_store = ChromaVectorStore(settings)
    try:
        result = recover_document_deletions(
            SessionLocal,
            vector_store,
            storage,
            lease_seconds=settings.document_deletion_lease_seconds,
        )
    finally:
        vector_store.close()
    return 0 if result.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(run())
