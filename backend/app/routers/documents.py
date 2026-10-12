"""Authenticated document upload routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.document import DocumentResponse
from app.services.document_service import (
    DocumentPersistenceError,
    DocumentStorageError,
    DocumentTooLargeError,
    EmptyDocumentError,
    InvalidDocumentContentError,
    InvalidDocumentMetadataError,
    UnsupportedDocumentTypeError,
    create_document,
)
from app.services.file_storage import FileStorage


router = APIRouter(prefix="/documents", tags=["Tài liệu"])


def get_file_storage() -> FileStorage:
    """Provide configured private storage for one request."""

    return FileStorage.from_settings()


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
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Chỉ hỗ trợ tệp PDF, DOCX và TXT.",
        ) from None
    except (DocumentStorageError, DocumentPersistenceError):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Không thể lưu tài liệu lúc này.",
        ) from None

    return DocumentResponse.model_validate(document)
