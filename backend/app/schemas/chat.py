"""Public request and response schemas for authenticated RAG chat."""

from datetime import datetime

from pydantic import BaseModel, Field


class ChatAskRequest(BaseModel):
    """One question about an owned, indexed document."""

    document_id: int = Field(gt=0)
    # Length/blank validation stays in the service so error responses do not
    # echo potentially sensitive question text through validation details.
    question: str
    session_id: int | None = Field(default=None, gt=0)


class ChatCitationResponse(BaseModel):
    """Safe citation metadata backed by a document chunk."""

    chunk_id: int
    chunk_index: int
    page_number: int | None
    citation_order: int


class ChatCitationDetailResponse(BaseModel):
    """Original PostgreSQL content for one authorized citation."""

    chunk_id: int
    document_id: int
    chunk_index: int
    content: str
    page_number: int | None
    citation_order: int


class ChatAskResponse(BaseModel):
    """Persisted result of one successful RAG chat turn."""

    session_id: int
    user_message_id: int
    assistant_message_id: int
    answer_text: str
    model_name: str
    citations: list[ChatCitationResponse]


class ChatSessionResponse(BaseModel):
    """Conversation summary without message content."""

    id: int
    document_id: int
    title: str
    created_at: datetime
    updated_at: datetime


class ChatSessionListResponse(BaseModel):
    """Offset-paginated sessions for one owned document."""

    items: list[ChatSessionResponse]
    total: int
    limit: int
    offset: int


class ChatMessageResponse(BaseModel):
    """One ordered message and its verified assistant citations."""

    id: int
    session_id: int
    sequence_no: int
    role: str
    content: str
    created_at: datetime
    citations: list[ChatCitationResponse]


class ChatMessageListResponse(BaseModel):
    """Offset-paginated history for one owned session."""

    session_id: int
    items: list[ChatMessageResponse]
    total: int
    limit: int
    offset: int


class ChatMessageCursorListResponse(BaseModel):
    """Cursor-paginated recent history for one owned session."""

    session_id: int
    items: list[ChatMessageResponse]
    total: int
    limit: int
    next_before_sequence_no: int | None
    has_more: bool
