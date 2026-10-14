"""Authenticated document summary generation and history routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.summary import SummaryResources, get_summary_resources
from app.models.user import User
from app.schemas.summary import (
    DocumentSummaryGenerateRequest,
    DocumentSummaryGenerateResponse,
    DocumentSummaryListResponse,
)
from app.services.summary.document_summary import (
    DocumentSummaryConflictError,
    DocumentSummaryDeadlineExceededError,
    DocumentSummaryGenerationError,
    DocumentSummaryLimitError,
    DocumentSummaryPersistenceError,
    InvalidDocumentSummaryRequestError,
    SummaryDocumentHasNoChunksError,
    SummaryDocumentNotFoundError,
    SummaryDocumentNotReadyError,
    list_document_summaries,
    summarize_document,
)
from app.services.summary.concurrency import (
    SummaryConcurrencyError,
    SummaryConcurrencyLimitError,
    SummaryGenerationBusyError,
)
from app.services.summary.gemini_summary import (
    GeminiSummaryBlockedError,
    GeminiSummaryConfigurationError,
    GeminiSummaryError,
    GeminiSummaryRateLimitError,
    GeminiSummaryRequestError,
    GeminiSummaryTimeoutError,
    InvalidGeminiSummaryResponseError,
    InvalidSummaryProviderInputError,
)


router = APIRouter(prefix="/summaries", tags=["Tóm tắt tài liệu"])


@router.post("/generate", response_model=DocumentSummaryGenerateResponse)
def generate_owned_document_summary(
    payload: DocumentSummaryGenerateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    resources: Annotated[SummaryResources, Depends(get_summary_resources)],
) -> DocumentSummaryGenerateResponse:
    """Generate or return one cached summary for an owned document."""

    try:
        result = summarize_document(
            db,
            resources.provider,
            document_id=payload.document_id,
            user_id=current_user.id,
            summary_type=payload.summary_type.value,
            concurrency_limits=resources.concurrency_limits,
            deadline_seconds=resources.deadline_seconds,
        )
    except SummaryDocumentNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy tài liệu.",
        ) from None
    except (
        SummaryDocumentNotReadyError,
        SummaryDocumentHasNoChunksError,
        DocumentSummaryConflictError,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Tài liệu chưa sẵn sàng để tóm tắt hoặc đang được cập nhật.",
        ) from None
    except InvalidDocumentSummaryRequestError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Yêu cầu tóm tắt không hợp lệ.",
        ) from None
    except DocumentSummaryLimitError:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Tài liệu vượt giới hạn xử lý tóm tắt an toàn.",
        ) from None
    except DocumentSummaryDeadlineExceededError:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=(
                "Quá trình tóm tắt đã vượt quá thời gian cho phép. "
                "Vui lòng thử lại sau."
            ),
        ) from None
    except SummaryGenerationBusyError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Bản tóm tắt này đang được tạo bởi một yêu cầu khác.",
        ) from None
    except SummaryConcurrencyLimitError:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "Hệ thống đang xử lý quá nhiều yêu cầu tóm tắt. "
                "Vui lòng thử lại sau."
            ),
            headers={"Retry-After": "5"},
        ) from None
    except GeminiSummaryRateLimitError:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Hạn mức dịch vụ AI tạm thời không khả dụng.",
        ) from None
    except (
        GeminiSummaryTimeoutError,
        GeminiSummaryBlockedError,
        GeminiSummaryConfigurationError,
        GeminiSummaryRequestError,
        InvalidGeminiSummaryResponseError,
        InvalidSummaryProviderInputError,
        DocumentSummaryGenerationError,
        GeminiSummaryError,
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Dịch vụ tóm tắt AI tạm thời không khả dụng.",
        ) from None
    except DocumentSummaryPersistenceError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Không thể lưu bản tóm tắt lúc này.",
        ) from None
    except SummaryConcurrencyError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Dịch vụ điều phối tóm tắt tạm thời không khả dụng.",
        ) from None
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Không thể hoàn tất yêu cầu tóm tắt lúc này.",
        ) from None
    return DocumentSummaryGenerateResponse.model_validate(result)


@router.get("", response_model=DocumentSummaryListResponse)
def get_owned_document_summaries(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    document_id: Annotated[int, Query(gt=0)],
) -> DocumentSummaryListResponse:
    """List stored summaries without initializing any AI dependency."""

    try:
        result = list_document_summaries(
            db,
            document_id=document_id,
            user_id=current_user.id,
        )
    except SummaryDocumentNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy tài liệu.",
        ) from None
    except (InvalidDocumentSummaryRequestError,):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Mã tài liệu không hợp lệ.",
        ) from None
    except DocumentSummaryPersistenceError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Không thể tải danh sách tóm tắt lúc này.",
        ) from None
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Không thể tải danh sách tóm tắt lúc này.",
        ) from None
    return DocumentSummaryListResponse.model_validate(result, from_attributes=True)
