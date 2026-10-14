"""Authenticated synchronous RAG chat and history routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.rag import RagChatResources, get_rag_chat_resources
from app.models.user import User
from app.schemas.chat import (
    ChatAskRequest,
    ChatAskResponse,
    ChatCitationDetailResponse,
    ChatMessageCursorListResponse,
    ChatMessageListResponse,
    ChatSessionListResponse,
)
from app.services.rag.chat_history import (
    ChatHistoryInfrastructureError,
    ChatHistoryNotFoundError,
    get_chat_citation_detail,
    list_chat_messages,
    list_chat_messages_cursor,
    list_chat_sessions,
)
from app.services.rag.chat_service import (
    ChatAnswerError,
    ChatCapacityLimitError,
    ChatConcurrencyError,
    ChatCoordinationError,
    ChatDeadlineExceededError,
    ChatDocumentNotFoundError,
    ChatDocumentNotReadyError,
    ChatPersistenceError,
    ChatRateLimitError,
    ChatRetrievalError,
    ChatSessionNotFoundError,
    InvalidChatCitationError,
    InvalidChatRequestError,
    ask_document,
)


router = APIRouter(prefix="/chat", tags=["Hỏi đáp tài liệu"])


@router.post("/ask", response_model=ChatAskResponse)
def ask_owned_document(
    payload: ChatAskRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    resources: Annotated[RagChatResources, Depends(get_rag_chat_resources)],
) -> ChatAskResponse:
    """Synchronously answer a question about one owned indexed document."""

    try:
        result = ask_document(
            db,
            resources.retrieval_service,
            resources.answer_provider,
            document_id=payload.document_id,
            user_id=current_user.id,
            question=payload.question,
            session_id=payload.session_id,
            concurrency_coordinator=resources.concurrency_coordinator,
            concurrency_limits=resources.concurrency_limits,
            deadline_seconds=resources.deadline_seconds,
            clock=resources.clock,
        )
    except (ChatDocumentNotFoundError, ChatSessionNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy tài liệu hoặc phiên hội thoại.",
        ) from None
    except (ChatDocumentNotReadyError, ChatConcurrencyError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Tài liệu chưa sẵn sàng hoặc hội thoại đang được cập nhật.",
        ) from None
    except InvalidChatRequestError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Câu hỏi hoặc thông tin phiên hội thoại không hợp lệ.",
        ) from None
    except ChatRateLimitError:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Hạn mức dịch vụ AI tạm thời không khả dụng.",
        ) from None
    except ChatCapacityLimitError:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "Hệ thống đang xử lý quá nhiều yêu cầu hỏi đáp. "
                "Vui lòng thử lại sau."
            ),
            headers={"Retry-After": "5"},
        ) from None
    except ChatCoordinationError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Không thể điều phối yêu cầu hỏi đáp lúc này.",
        ) from None
    except ChatDeadlineExceededError:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=(
                "Yêu cầu hỏi đáp đã vượt quá thời gian xử lý. "
                "Vui lòng thử lại sau."
            ),
        ) from None
    except (ChatRetrievalError, ChatAnswerError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Dịch vụ hỏi đáp tài liệu tạm thời không khả dụng.",
        ) from None
    except (InvalidChatCitationError, ChatPersistenceError):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Không thể hoàn tất lượt hỏi đáp lúc này.",
        ) from None
    return ChatAskResponse.model_validate(result, from_attributes=True)


@router.get("/sessions", response_model=ChatSessionListResponse)
def get_owned_chat_sessions(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    document_id: Annotated[int, Query(gt=0)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ChatSessionListResponse:
    """List recent sessions belonging to one owned document."""

    try:
        page = list_chat_sessions(
            db,
            document_id=document_id,
            user_id=current_user.id,
            limit=limit,
            offset=offset,
        )
    except ChatHistoryNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy tài liệu.",
        ) from None
    except ChatHistoryInfrastructureError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Không thể tải danh sách hội thoại lúc này.",
        ) from None
    return ChatSessionListResponse(
        items=[
            {
                "id": item.id,
                "document_id": item.document_id,
                "title": item.title,
                "created_at": item.created_at,
                "updated_at": item.updated_at,
            }
            for item in page.items
        ],
        total=page.total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/sessions/{session_id}/messages",
    response_model=ChatMessageListResponse,
)
def get_owned_chat_messages(
    session_id: Annotated[int, Path(gt=0)],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ChatMessageListResponse:
    """Return ordered messages and verified citations for one owned session."""

    try:
        page = list_chat_messages(
            db,
            session_id=session_id,
            user_id=current_user.id,
            limit=limit,
            offset=offset,
        )
    except ChatHistoryNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy phiên hội thoại.",
        ) from None
    except ChatHistoryInfrastructureError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Không thể tải lịch sử hội thoại lúc này.",
        ) from None
    return ChatMessageListResponse.model_validate(
        {
            "session_id": page.session_id,
            "items": page.items,
            "total": page.total,
            "limit": limit,
            "offset": offset,
        },
        from_attributes=True,
    )


@router.get(
    "/sessions/{session_id}/messages/cursor",
    response_model=ChatMessageCursorListResponse,
)
def get_owned_chat_messages_cursor(
    session_id: Annotated[int, Path(gt=0)],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=50)] = 50,
    before_sequence_no: Annotated[int | None, Query(ge=0)] = None,
) -> ChatMessageCursorListResponse:
    """Return recent messages using a stable sequence-number cursor."""

    try:
        page = list_chat_messages_cursor(
            db,
            session_id=session_id,
            user_id=current_user.id,
            limit=limit,
            before_sequence_no=before_sequence_no,
        )
    except ChatHistoryNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy phiên hội thoại.",
        ) from None
    except ChatHistoryInfrastructureError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Không thể tải lịch sử hội thoại lúc này.",
        ) from None
    return ChatMessageCursorListResponse.model_validate(
        {
            "session_id": page.session_id,
            "items": page.items,
            "total": page.total,
            "limit": limit,
            "next_before_sequence_no": page.next_before_sequence_no,
            "has_more": page.has_more,
        },
        from_attributes=True,
    )


@router.get(
    "/citations/{chunk_id}",
    response_model=ChatCitationDetailResponse,
)
def get_owned_chat_citation(
    chunk_id: Annotated[int, Path(gt=0)],
    session_id: Annotated[int, Query(gt=0)],
    message_id: Annotated[int, Query(gt=0)],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ChatCitationDetailResponse:
    """Return original chunk text for one verified assistant citation."""

    try:
        detail = get_chat_citation_detail(
            db,
            chunk_id=chunk_id,
            session_id=session_id,
            message_id=message_id,
            user_id=current_user.id,
        )
    except ChatHistoryNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy nguồn trích dẫn.",
        ) from None
    except ChatHistoryInfrastructureError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Không thể tải nguồn trích dẫn lúc này.",
        ) from None
    return ChatCitationDetailResponse.model_validate(detail, from_attributes=True)
