"""Isolated API and query tests for the administrator dashboard."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
)
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.core.security import create_access_token
from app.db.session import get_db
from app.main import app
from app.models.chat_session import ChatSession
from app.models.document import Document
from app.models.document_deletion_job import DocumentDeletionJob
from app.models.document_summary import DocumentSummary
from app.models.user import User
from app.services.admin_dashboard import get_admin_dashboard_activity


UTC = timezone.utc


@pytest.fixture
def admin_dashboard_session_factory(
    client: TestClient,
) -> Iterator[sessionmaker[Session]]:
    """Use an isolated in-memory database for every Admin Dashboard test."""

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    metadata = MetaData()
    Table(
        "users",
        metadata,
        Column("id", BigInteger, primary_key=True),
        Column("full_name", String(100), nullable=False),
        Column("username", String(30), nullable=False),
        Column("password_hash", Text, nullable=False),
        Column("role", String(10), nullable=False),
        Column("is_active", Boolean, nullable=False),
        Column("token_version", Integer, nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
    )
    for table in (
        Document.__table__,
        DocumentSummary.__table__,
        ChatSession.__table__,
        DocumentDeletionJob.__table__,
    ):
        table.to_metadata(metadata)
    metadata.create_all(engine)
    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )

    def override() -> Iterator[Session]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override
    yield factory
    app.dependency_overrides.pop(get_db, None)
    engine.dispose()


def add_user(
    session: Session,
    *,
    user_id: int,
    username: str,
    role: str = "USER",
    is_active: bool = True,
    token_version: int = 0,
    created_at: datetime | None = None,
    password_hash: str = "test-only-hash",
) -> User:
    user = User(
        id=user_id,
        full_name=f"User {user_id}",
        username=username,
        password_hash=password_hash,
        role=role,
        is_active=is_active,
        token_version=token_version,
        created_at=created_at or datetime.now(UTC),
    )
    session.add(user)
    session.flush()
    return user


def add_document(
    session: Session,
    *,
    document_id: int,
    user_id: int,
    status: str = "READY",
    rag_status: str = "READY",
    created_at: datetime | None = None,
    processed_at: datetime | None = None,
    indexed_at: datetime | None = None,
    storage_key: str | None = None,
) -> Document:
    timestamp = created_at or datetime.now(UTC)
    document = Document(
        id=document_id,
        user_id=user_id,
        title=f"Document {document_id}",
        original_filename=f"document-{document_id}.pdf",
        storage_key=storage_key or f"users/{user_id}/document-{document_id}.pdf",
        file_type="PDF",
        mime_type="application/pdf",
        file_size=100,
        status=status,
        rag_status=rag_status,
        created_at=timestamp,
        updated_at=timestamp,
        processed_at=processed_at,
        indexed_at=indexed_at,
    )
    session.add(document)
    session.flush()
    return document


def add_summary(
    session: Session,
    *,
    summary_id: int,
    document_id: int,
    created_at: datetime,
    content: str = "Safe summary",
    summary_type: str = "SHORT",
) -> DocumentSummary:
    summary = DocumentSummary(
        id=summary_id,
        document_id=document_id,
        summary_type=summary_type,
        content=content,
        model_name="fake-model",
        created_at=created_at,
        updated_at=created_at,
    )
    session.add(summary)
    session.flush()
    return summary


def add_chat_session(
    session: Session,
    *,
    session_id: int,
    document_id: int,
    created_at: datetime,
) -> ChatSession:
    chat_session = ChatSession(
        id=session_id,
        document_id=document_id,
        title=f"Session {session_id}",
        created_at=created_at,
        updated_at=created_at,
    )
    session.add(chat_session)
    session.flush()
    return chat_session


def add_tombstone(
    session: Session,
    *,
    job_id: int,
    document_id: int,
    user_id: int,
    status: str = "PENDING",
    completed_at: datetime | None = None,
) -> DocumentDeletionJob:
    completed = status == "COMPLETED"
    job = DocumentDeletionJob(
        id=job_id,
        document_id=document_id,
        user_id=user_id,
        storage_key=None if completed else f"users/{user_id}/deleted.pdf",
        status=status,
        current_step="DONE" if completed else "VECTOR_CLEANUP",
        attempt_count=1,
        completed_at=completed_at,
        created_at=(completed_at or datetime.now(UTC)) - timedelta(minutes=1),
        updated_at=completed_at or datetime.now(UTC),
    )
    session.add(job)
    session.flush()
    return job


def auth_header(user: User, *, token_version: int | None = None) -> dict[str, str]:
    version = user.token_version if token_version is None else token_version
    token = create_access_token(user.id, version)
    return {"Authorization": f"Bearer {token}"}


def test_admin_endpoints_require_authentication_and_admin_role(
    client: TestClient,
    admin_dashboard_session_factory: sessionmaker[Session],
) -> None:
    with admin_dashboard_session_factory() as session:
        standard_user = add_user(session, user_id=1, username="standard")
        admin = add_user(session, user_id=2, username="admin", role="ADMIN")
        session.commit()

    for path in (
        "/admin/dashboard/overview",
        "/admin/dashboard/activity",
        "/admin/dashboard/recent-activities",
    ):
        assert client.get(path).status_code == 401
        assert client.get(
            path,
            headers={"Authorization": "Bearer invalid-token"},
        ).status_code == 401
        assert client.get(path, headers=auth_header(standard_user)).status_code == 403
        assert client.get(path, headers=auth_header(admin)).status_code == 200


def test_admin_endpoints_reject_inactive_stale_and_forged_role_tokens(
    client: TestClient,
    admin_dashboard_session_factory: sessionmaker[Session],
) -> None:
    with admin_dashboard_session_factory() as session:
        inactive = add_user(
            session,
            user_id=1,
            username="inactive_admin",
            role="ADMIN",
            is_active=False,
        )
        current_admin = add_user(
            session,
            user_id=2,
            username="current_admin",
            role="ADMIN",
            token_version=3,
        )
        standard_user = add_user(session, user_id=3, username="forged")
        session.commit()

    assert client.get(
        "/admin/dashboard/overview",
        headers=auth_header(inactive),
    ).status_code == 401
    assert client.get(
        "/admin/dashboard/overview",
        headers=auth_header(current_admin, token_version=2),
    ).status_code == 401

    settings = get_settings()
    now = datetime.now(UTC)
    forged_token = jwt.encode(
        {
            "sub": str(standard_user.id),
            "iat": now,
            "exp": now + timedelta(minutes=30),
            "type": "access",
            "role": "ADMIN",
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "ver": standard_user.token_version,
        },
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    assert client.get(
        "/admin/dashboard/overview",
        headers={"Authorization": f"Bearer {forged_token}"},
    ).status_code == 403


def test_overview_counts_live_rows_without_join_or_processing_duplicates(
    client: TestClient,
    admin_dashboard_session_factory: sessionmaker[Session],
) -> None:
    with admin_dashboard_session_factory() as session:
        admin = add_user(session, user_id=1, username="admin", role="ADMIN")
        owner = add_user(session, user_id=2, username="owner", is_active=False)
        add_document(
            session,
            document_id=1,
            user_id=owner.id,
            status="PROCESSING",
            rag_status="INDEXING",
        )
        add_document(
            session,
            document_id=2,
            user_id=owner.id,
            status="READY",
            rag_status="INDEXING",
        )
        add_document(session, document_id=3, user_id=owner.id)
        add_document(session, document_id=4, user_id=owner.id)
        timestamp = datetime.now(UTC)
        add_chat_session(
            session,
            session_id=1,
            document_id=3,
            created_at=timestamp,
        )
        add_chat_session(
            session,
            session_id=2,
            document_id=3,
            created_at=timestamp,
        )
        add_chat_session(
            session,
            session_id=3,
            document_id=4,
            created_at=timestamp,
        )
        add_summary(
            session,
            summary_id=1,
            document_id=3,
            created_at=timestamp,
        )
        add_summary(
            session,
            summary_id=2,
            document_id=3,
            created_at=timestamp,
            summary_type="STANDARD",
        )
        add_tombstone(
            session,
            job_id=1,
            document_id=4,
            user_id=owner.id,
        )
        session.commit()

    response = client.get(
        "/admin/dashboard/overview",
        headers=auth_header(admin),
    )

    assert response.status_code == 200
    assert response.json() == {
        "user_count": 2,
        "document_count": 3,
        "chat_session_count": 2,
        "processing_document_count": 2,
    }


def test_activity_zero_fills_utc_days_and_honors_boundaries_and_tombstones(
    admin_dashboard_session_factory: sessionmaker[Session],
) -> None:
    now = datetime(2026, 10, 15, 12, tzinfo=UTC)
    first_day = datetime(2026, 10, 9, 0, tzinfo=UTC)
    range_end = datetime(2026, 10, 16, 0, tzinfo=UTC)
    with admin_dashboard_session_factory() as session:
        add_user(
            session,
            user_id=1,
            username="before",
            created_at=first_day - timedelta(microseconds=1),
        )
        owner = add_user(
            session,
            user_id=2,
            username="boundary",
            created_at=first_day,
        )
        add_user(
            session,
            user_id=3,
            username="after",
            created_at=range_end,
        )
        add_document(
            session,
            document_id=1,
            user_id=owner.id,
            created_at=first_day,
        )
        add_document(
            session,
            document_id=2,
            user_id=owner.id,
            created_at=now,
        )
        add_tombstone(
            session,
            job_id=1,
            document_id=2,
            user_id=owner.id,
        )
        add_chat_session(
            session,
            session_id=1,
            document_id=1,
            created_at=now,
        )
        add_summary(
            session,
            summary_id=1,
            document_id=1,
            created_at=now,
        )
        session.commit()

        result = get_admin_dashboard_activity(session, now=now)

    assert len(result.items) == 7
    assert [item.date.isoformat() for item in result.items] == [
        "2026-10-09",
        "2026-10-10",
        "2026-10-11",
        "2026-10-12",
        "2026-10-13",
        "2026-10-14",
        "2026-10-15",
    ]
    assert result.items[0].registered_user_count == 1
    assert result.items[0].uploaded_document_count == 1
    assert result.items[1].registered_user_count == 0
    assert result.items[-1].registered_user_count == 0
    assert result.items[-1].uploaded_document_count == 0
    assert result.items[-1].created_chat_session_count == 1
    assert result.items[-1].generated_summary_count == 1


def test_recent_activities_are_stable_limited_and_content_safe(
    client: TestClient,
    admin_dashboard_session_factory: sessionmaker[Session],
) -> None:
    timestamp = datetime(2026, 10, 15, 8, tzinfo=UTC)
    secrets = (
        "sensitive-password-hash",
        "sensitive-storage-key",
        "sensitive-summary-content",
        "sensitive-chat-content",
        "token_version",
        "password_hash",
        "storage_key",
    )
    with admin_dashboard_session_factory() as session:
        admin = add_user(
            session,
            user_id=1,
            username="admin",
            role="ADMIN",
            created_at=timestamp,
            password_hash=secrets[0],
        )
        document = add_document(
            session,
            document_id=1,
            user_id=admin.id,
            created_at=timestamp,
            processed_at=timestamp,
            indexed_at=timestamp,
            storage_key=secrets[1],
        )
        add_summary(
            session,
            summary_id=1,
            document_id=document.id,
            created_at=timestamp,
            content=secrets[2],
        )
        add_chat_session(
            session,
            session_id=1,
            document_id=document.id,
            created_at=timestamp,
        )
        session.commit()

    response = client.get(
        "/admin/dashboard/recent-activities?limit=3",
        headers=auth_header(admin),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["limit"] == 3
    assert body["is_audit_log"] is False
    assert len(body["items"]) == 3
    assert [item["activity_type"] for item in body["items"]] == [
        "CHAT_SESSION_CREATED",
        "DOCUMENT_INDEXED",
        "DOCUMENT_PROCESSED",
    ]
    serialized = response.text
    assert all(secret not in serialized for secret in secrets)
    assert client.get(
        "/admin/dashboard/recent-activities?limit=0",
        headers=auth_header(admin),
    ).status_code == 422
    assert client.get(
        "/admin/dashboard/recent-activities?limit=51",
        headers=auth_header(admin),
    ).status_code == 422


def test_recent_activities_exclude_tombstoned_document_sources(
    client: TestClient,
    admin_dashboard_session_factory: sessionmaker[Session],
) -> None:
    timestamp = datetime.now(UTC)
    with admin_dashboard_session_factory() as session:
        admin = add_user(session, user_id=1, username="admin", role="ADMIN")
        add_document(
            session,
            document_id=1,
            user_id=admin.id,
            created_at=timestamp,
            processed_at=timestamp,
            indexed_at=timestamp,
        )
        add_summary(
            session,
            summary_id=1,
            document_id=1,
            created_at=timestamp,
        )
        add_chat_session(
            session,
            session_id=1,
            document_id=1,
            created_at=timestamp,
        )
        add_tombstone(
            session,
            job_id=1,
            document_id=1,
            user_id=admin.id,
        )
        session.commit()

    response = client.get(
        "/admin/dashboard/recent-activities?limit=50",
        headers=auth_header(admin),
    )

    assert response.status_code == 200
    assert [item["activity_type"] for item in response.json()["items"]] == [
        "USER_REGISTERED"
    ]

