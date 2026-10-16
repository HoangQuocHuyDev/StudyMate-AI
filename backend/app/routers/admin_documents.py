"""Administrator-only read access to system-wide document metadata."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import require_roles
from app.models.user import User
from app.schemas.admin_documents import (
    AdminDocumentDetailResponse,
    AdminDocumentItemResponse,
    AdminDocumentListResponse,
)
from app.services.admin_documents import (
    AdminDocumentNotFoundError,
    AdminDocumentQueryError,
    get_admin_document,
    list_admin_documents,
)


router = APIRouter(prefix="/admin/documents", tags=["Quản trị tài liệu"])
AdminUser = Annotated[User, Depends(require_roles("ADMIN"))]
DatabaseSession = Annotated[Session, Depends(get_db)]


def _query_failed() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Không thể tải thông tin tài liệu lúc này.",
    )


@router.get("", response_model=AdminDocumentListResponse)
def get_documents(
    current_admin: AdminUser,
    db: DatabaseSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    search: Annotated[str, Query(max_length=255)] = "",
    file_type: Annotated[Literal["PDF", "DOCX"] | None, Query()] = None,
    status_filter: Annotated[
        Literal["UPLOADED", "PROCESSING", "READY", "FAILED"] | None,
        Query(alias="status"),
    ] = None,
    rag_status: Annotated[
        Literal["PENDING", "INDEXING", "READY", "FAILED"] | None,
        Query(),
    ] = None,
) -> AdminDocumentListResponse:
    """List non-tombstoned document metadata across all owners."""

    del current_admin
    try:
        page = list_admin_documents(
            db,
            limit=limit,
            offset=offset,
            search=search,
            file_type=file_type,
            status=status_filter,
            rag_status=rag_status,
        )
    except AdminDocumentQueryError:
        raise _query_failed() from None

    return AdminDocumentListResponse(
        items=[
            AdminDocumentItemResponse.model_validate(item)
            for item in page.items
        ],
        total=page.total,
        limit=limit,
        offset=offset,
    )


@router.get("/{document_id}", response_model=AdminDocumentDetailResponse)
def get_document_detail(
    document_id: Annotated[int, Path(gt=0)],
    current_admin: AdminUser,
    db: DatabaseSession,
) -> AdminDocumentDetailResponse:
    """Return metadata only; this endpoint never reads stored document bytes."""

    del current_admin
    try:
        document = get_admin_document(db, document_id=document_id)
    except AdminDocumentNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy tài liệu.",
        ) from None
    except AdminDocumentQueryError:
        raise _query_failed() from None
    return AdminDocumentDetailResponse.model_validate(document)
