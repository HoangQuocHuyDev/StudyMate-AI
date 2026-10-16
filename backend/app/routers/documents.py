"""Authenticated document routes."""

from typing import Annotated
import unicodedata
from urllib.parse import quote

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.rag import (
    DocumentDeletionResources,
    RagIndexingResources,
    get_document_deletion_resources,
    get_rag_indexing_resources,
)
from app.models.user import User
from app.schemas.document import (
    DocumentDetailResponse,
    DocumentFileType,
    DocumentIndexingResponse,
    DocumentListResponse,
    DocumentPreviewResponse,
    DocumentProcessingStatusResponse,
    DocumentRagStatusResponse,
    DocumentResponse,
)
from app.services.document_processing import (
    DocumentNotFoundError,
    DocumentNotProcessableError,
    DocumentProcessingFailedError,
    DocumentProcessingInfrastructureError,
    get_document_processing_status,
    process_document,
    retry_document,
)
from app.services.document_preview import (
    DocumentPreviewNotFoundError,
    DocumentPreviewTooLargeError,
    DocumentPreviewUnavailableError,
    UnsupportedDocumentPreviewError,
    get_owned_docx_preview,
)
from app.services.document_deletion import (
    DocumentDeletionConflictError,
    DocumentDeletionExternalError,
    DocumentDeletionInfrastructureError,
    DocumentDeletionNotFoundError,
    delete_owned_document,
)
from app.services.document_service import (
    DocumentPersistenceError,
    DocumentQueryError,
    DocumentStorageError,
    DocumentTooLargeError,
    EmptyDocumentError,
    InvalidDocumentContentError,
    InvalidDocumentMetadataError,
    OwnedDocumentNotFoundError,
    UnsupportedDocumentTypeError,
    create_document,
    get_owned_document,
    list_documents,
)
from app.services.file_storage import FileStorage, FileStorageError
from app.services.rag.document_indexing import (
    DocumentIndexingFailedError,
    DocumentIndexingInfrastructureError,
    DocumentIndexingNotFoundError,
    DocumentNotIndexableError,
    get_document_rag_status,
    index_document,
)


router = APIRouter(prefix="/documents", tags=["Tài liệu"])

_DOWNLOAD_MIME_TYPES = {
    "PDF": "application/pdf",
    "DOCX": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def get_file_storage() -> FileStorage:
    """Provide configured private storage for one request."""

    return FileStorage.from_settings()


def _get_owned_document_or_404(
    db: Session,
    *,
    document_id: int,
    user_id: int,
):
    try:
        return get_owned_document(
            db,
            document_id=document_id,
            user_id=user_id,
        )
    except OwnedDocumentNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy tài liệu.",
        ) from None
    except DocumentQueryError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Không thể lấy thông tin tài liệu lúc này.",
        ) from None


def _read_stored_document(storage: FileStorage, storage_key: str) -> bytes:
    try:
        with storage.open_binary(storage_key) as stream:
            return stream.read()
    except (FileStorageError, OSError):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Không thể đọc tệp tài liệu lúc này.",
        ) from None


def _content_disposition(disposition: str, filename: str) -> str:
    normalized = unicodedata.normalize("NFKD", filename)
    ascii_name = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_name = "".join(
        character
        for character in ascii_name
        if character >= " " and character not in {'"', "\\", ";"}
    ).strip()
    if not ascii_name:
        ascii_name = "document"
    encoded_name = quote(filename, safe="")
    return (
        f'{disposition}; filename="{ascii_name}"; '
        f"filename*=UTF-8''{encoded_name}"
    )


@router.get("", response_model=DocumentListResponse)
def get_documents(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 10,
    search: Annotated[str | None, Query(max_length=255)] = None,
    file_type: Annotated[DocumentFileType | None, Query()] = None,
) -> DocumentListResponse:
    """List metadata owned by the authenticated user."""

    try:
        result = list_documents(
            db,
            user_id=current_user.id,
            page=page,
            page_size=page_size,
            search=search,
            file_type=file_type.value if file_type is not None else None,
        )
    except DocumentQueryError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Không thể lấy danh sách tài liệu lúc này.",
        ) from None

    return DocumentListResponse(
        items=[DocumentResponse.model_validate(item) for item in result.items],
        page=page,
        page_size=page_size,
        total=result.total,
        total_pages=(result.total + page_size - 1) // page_size,
    )


@router.get("/{document_id}", response_model=DocumentDetailResponse)
def get_document_detail(
    document_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DocumentDetailResponse:
    """Return detailed metadata for one document owned by the caller."""

    document = _get_owned_document_or_404(
        db,
        document_id=document_id,
        user_id=current_user.id,
    )
    return DocumentDetailResponse.model_validate(document)


@router.get("/{document_id}/view")
def view_document_pdf(
    document_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    storage: Annotated[FileStorage, Depends(get_file_storage)],
) -> Response:
    """Return one owned PDF inline without exposing its storage location."""

    document = _get_owned_document_or_404(
        db,
        document_id=document_id,
        user_id=current_user.id,
    )
    if document.file_type != "PDF":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Chỉ tài liệu PDF mới có thể xem trực tiếp.",
        )
    content = _read_stored_document(storage, document.storage_key)
    return Response(
        content=content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": _content_disposition(
                "inline",
                document.original_filename,
            ),
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/{document_id}/preview", response_model=DocumentPreviewResponse)
def preview_document_docx(
    document_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    storage: Annotated[FileStorage, Depends(get_file_storage)],
) -> DocumentPreviewResponse:
    """Return a read-only plain-text preview of one owned DOCX source file."""

    try:
        preview = get_owned_docx_preview(
            db,
            storage,
            document_id=document_id,
            user_id=current_user.id,
        )
    except DocumentPreviewNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy tài liệu.",
        ) from None
    except UnsupportedDocumentPreviewError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Chỉ hỗ trợ xem trước nội dung tài liệu DOCX.",
        ) from None
    except DocumentPreviewTooLargeError:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Nội dung tài liệu vượt quá giới hạn xem trước.",
        ) from None
    except DocumentPreviewUnavailableError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Không thể tạo bản xem trước tài liệu lúc này.",
        ) from None

    return DocumentPreviewResponse.model_validate(preview)


@router.get("/{document_id}/download")
def download_document(
    document_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    storage: Annotated[FileStorage, Depends(get_file_storage)],
) -> Response:
    """Download one owned PDF or DOCX using safe response headers."""

    document = _get_owned_document_or_404(
        db,
        document_id=document_id,
        user_id=current_user.id,
    )
    mime_type = _DOWNLOAD_MIME_TYPES.get(document.file_type)
    if mime_type is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Chỉ hỗ trợ tải xuống tài liệu PDF hoặc DOCX.",
        )
    content = _read_stored_document(storage, document.storage_key)
    return Response(
        content=content,
        media_type=mime_type,
        headers={
            "Content-Disposition": _content_disposition(
                "attachment",
                document.original_filename,
            ),
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_document(
    document_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    storage: Annotated[FileStorage, Depends(get_file_storage)],
    resources: Annotated[
        DocumentDeletionResources,
        Depends(get_document_deletion_resources),
    ],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    """Synchronously complete one durable, owner-scoped deletion job."""

    try:
        delete_owned_document(
            db,
            resources.vector_store,
            storage,
            document_id=document_id,
            user_id=current_user.id,
            lease_seconds=settings.document_deletion_lease_seconds,
        )
    except DocumentDeletionNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="KhÃ´ng tÃ¬m tháº¥y tÃ i liá»‡u.",
        ) from None
    except DocumentDeletionConflictError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="TÃ i liá»‡u Ä‘ang Ä‘Æ°á»£c xá»­ lÃ½ hoáº·c xÃ³a.",
        ) from None
    except DocumentDeletionExternalError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Dá»‹ch vá»¥ lÆ°u trá»¯ táº¡m thá»i khÃ´ng kháº£ dá»¥ng.",
        ) from None
    except DocumentDeletionInfrastructureError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="KhÃ´ng thá»ƒ xÃ³a tÃ i liá»‡u lÃºc nÃ y.",
        ) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/upload",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
def upload_document(
    file: Annotated[UploadFile, File(...)],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    storage: Annotated[FileStorage, Depends(get_file_storage)],
    title: Annotated[str | None, Form()] = None,
) -> DocumentResponse:
    """Validate and store one document for the authenticated user."""

    try:
        document = create_document(
            db,
            storage,
            file.file,
            filename=file.filename,
            content_type=file.content_type,
            title=title,
            user_id=current_user.id,
        )
    except InvalidDocumentMetadataError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tên tệp hoặc tiêu đề không hợp lệ.",
        ) from None
    except EmptyDocumentError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tệp tải lên không được để trống.",
        ) from None
    except InvalidDocumentContentError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nội dung tệp không đúng định dạng.",
        ) from None
    except DocumentTooLargeError:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Tệp vượt quá giới hạn dung lượng cho phép.",
        ) from None
    except UnsupportedDocumentTypeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Chỉ hỗ trợ tải lên tệp PDF hoặc DOCX hợp lệ.",
        ) from None
    except (DocumentStorageError, DocumentPersistenceError):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Không thể lưu tài liệu lúc này.",
        ) from None

    return DocumentResponse.model_validate(document)


def _processing_status_response(
    db: Session,
    *,
    document_id: int,
    user_id: int,
) -> DocumentProcessingStatusResponse:
    try:
        result = get_document_processing_status(
            db,
            document_id=document_id,
            user_id=user_id,
        )
    except DocumentNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy tài liệu.",
        ) from None
    except DocumentProcessingInfrastructureError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Không thể lấy trạng thái xử lý tài liệu lúc này.",
        ) from None
    return DocumentProcessingStatusResponse.model_validate(result)


@router.post(
    "/{document_id}/process",
    response_model=DocumentProcessingStatusResponse,
    status_code=status.HTTP_200_OK,
)
def process_owned_document(
    document_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    storage: Annotated[FileStorage, Depends(get_file_storage)],
) -> DocumentProcessingStatusResponse:
    """Synchronously process or intentionally retry one owned document."""

    try:
        try:
            process_document(
                db,
                storage,
                document_id=document_id,
                user_id=current_user.id,
            )
        except DocumentNotProcessableError:
            retry_document(
                db,
                storage,
                document_id=document_id,
                user_id=current_user.id,
            )
    except DocumentNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy tài liệu.",
        ) from None
    except DocumentNotProcessableError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Tài liệu không ở trạng thái có thể xử lý.",
        ) from None
    except DocumentProcessingFailedError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Không thể trích xuất hoặc xử lý nội dung tài liệu.",
        ) from None
    except DocumentProcessingInfrastructureError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Không thể hoàn tất xử lý tài liệu lúc này.",
        ) from None

    return _processing_status_response(
        db,
        document_id=document_id,
        user_id=current_user.id,
    )


@router.get(
    "/{document_id}/status",
    response_model=DocumentProcessingStatusResponse,
)
def get_owned_document_processing_status(
    document_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DocumentProcessingStatusResponse:
    """Return processing state and PostgreSQL chunk count for an owned document."""

    return _processing_status_response(
        db,
        document_id=document_id,
        user_id=current_user.id,
    )


@router.post(
    "/{document_id}/index",
    response_model=DocumentIndexingResponse,
    status_code=status.HTTP_200_OK,
)
def index_owned_document(
    document_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    resources: Annotated[
        RagIndexingResources,
        Depends(get_rag_indexing_resources),
    ],
) -> DocumentIndexingResponse:
    """Synchronously index an owned, processed document."""

    try:
        result = index_document(
            db,
            resources.embedder,
            resources.vector_store,
            document_id=document_id,
            user_id=current_user.id,
        )
    except DocumentIndexingNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy tài liệu.",
        ) from None
    except DocumentNotIndexableError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Tài liệu không ở trạng thái có thể lập chỉ mục.",
        ) from None
    except DocumentIndexingFailedError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Dịch vụ lập chỉ mục RAG tạm thời không khả dụng.",
        ) from None
    except DocumentIndexingInfrastructureError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Không thể cập nhật trạng thái lập chỉ mục lúc này.",
        ) from None
    return DocumentIndexingResponse.model_validate(result)


@router.get(
    "/{document_id}/rag-status",
    response_model=DocumentRagStatusResponse,
)
def get_owned_document_rag_status(
    document_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DocumentRagStatusResponse:
    """Return PostgreSQL RAG state for one owned document."""

    try:
        result = get_document_rag_status(
            db,
            document_id=document_id,
            user_id=current_user.id,
        )
    except DocumentIndexingNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy tài liệu.",
        ) from None
    except DocumentIndexingInfrastructureError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Không thể lấy trạng thái lập chỉ mục lúc này.",
        ) from None
    return DocumentRagStatusResponse.model_validate(result)
