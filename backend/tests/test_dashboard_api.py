"""Isolated API tests for authenticated dashboard aggregate counts."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone

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

from app.core.security import create_access_token
from app.db.session import get_db
from app.main import app
from app.models.chat_session import ChatSession
from app.models.document import Document
from app.models.document_deletion_job import DocumentDeletionJob
from app.models.document_summary import DocumentSummary
from app.models.user import User


def authorization_header(user: User) -> dict[str, str]:
    return {
        "Authorization": (
            f"Bearer {create_access_token(user.id, user.token_version)}"
        )
    }


@pytest.fixture
def dashboard_session_factory(
    client: TestClient,
) -> Iterator[sessionmaker[Session]]:
    """Use only an in-memory SQLite database for dashboard API tests."""

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
) -> User:
    user = User(
        id=user_id,
        full_name=f"User {user_id}",
        username=username,
        password_hash="test-only-hash",
        role="USER",
        is_active=True,
        token_version=0,
        created_at=datetime.now(timezone.utc),
    )
    session.add(user)
    session.flush()
    return user


def add_document(
    session: Session,
    *,
    document_id: int,
    user_id: int,
    status: str,
) -> Document:
    document = Document(
        id=document_id,
        user_id=user_id,
        title=f"Document {document_id}",
        original_filename=f"document-{document_id}.pdf",
        storage_key=f"users/{user_id}/document-{document_id}.pdf",
        file_type="PDF",
        mime_type="application/pdf",
        file_size=100,
        status=status,
        rag_status="PENDING",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    session.add(document)
    session.flush()
    return document


def add_summary(
    session: Session,
    *,
    document_id: int,
    summary_type: str,
) -> None:
    session.add(
        DocumentSummary(
            document_id=document_id,
            summary_type=summary_type,
            content=f"Summary {summary_type}",
            model_name="fake-model",
        )
    )


def add_chat_session(
    session: Session,
    *,
    document_id: int,
    title: str,
) -> None:
    session.add(ChatSession(document_id=document_id, title=title))


def get_overview(client: TestClient, user: User):
    return client.get(
        "/dashboard/overview",
        headers=authorization_header(user),
    )


def test_dashboard_requires_valid_jwt(
    client: TestClient,
    dashboard_session_factory: sessionmaker[Session],
) -> None:
    assert client.get("/dashboard/overview").status_code == 401
    response = client.get(
        "/dashboard/overview",
        headers={"Authorization": "Bearer invalid-token"},
    )
    assert response.status_code == 401


def test_dashboard_returns_zero_counts_for_user_without_data(
    client: TestClient,
    dashboard_session_factory: sessionmaker[Session],
) -> None:
    with dashboard_session_factory() as session:
        user = add_user(session, user_id=1, username="empty_user")
        session.commit()

    response = get_overview(client, user)

    assert response.status_code == 200
    assert response.json() == {
        "document_count": 0,
        "ready_document_count": 0,
        "summary_count": 0,
        "chat_session_count": 0,
    }


def test_dashboard_counts_each_record_without_join_multiplication(
    client: TestClient,
    dashboard_session_factory: sessionmaker[Session],
) -> None:
    with dashboard_session_factory() as session:
        user = add_user(session, user_id=1, username="owner")
        add_document(session, document_id=1, user_id=user.id, status="READY")
        add_document(session, document_id=2, user_id=user.id, status="UPLOADED")
        add_document(session, document_id=3, user_id=user.id, status="FAILED")
        add_summary(session, document_id=1, summary_type="SHORT")
        add_summary(session, document_id=1, summary_type="STANDARD")
        add_summary(session, document_id=1, summary_type="DETAILED")
        add_chat_session(session, document_id=1, title="Session 1")
        add_chat_session(session, document_id=1, title="Session 2")
        session.commit()

    response = get_overview(client, user)

    assert response.status_code == 200
    assert response.json() == {
        "document_count": 3,
        "ready_document_count": 1,
        "summary_count": 3,
        "chat_session_count": 2,
    }


def test_dashboard_isolates_users_and_excludes_active_deletion_jobs(
    client: TestClient,
    dashboard_session_factory: sessionmaker[Session],
) -> None:
    with dashboard_session_factory() as session:
        owner = add_user(session, user_id=1, username="owner")
        other = add_user(session, user_id=2, username="other")
        add_document(session, document_id=1, user_id=owner.id, status="READY")
        add_document(session, document_id=2, user_id=owner.id, status="READY")
        add_document(session, document_id=3, user_id=other.id, status="READY")
        add_summary(session, document_id=1, summary_type="SHORT")
        add_summary(session, document_id=2, summary_type="SHORT")
        add_summary(session, document_id=3, summary_type="SHORT")
        add_chat_session(session, document_id=1, title="Owner visible")
        add_chat_session(session, document_id=2, title="Owner deleting")
        add_chat_session(session, document_id=3, title="Other user")
        session.add(
            DocumentDeletionJob(
                document_id=2,
                user_id=owner.id,
                storage_key="users/1/document-2.pdf",
                status="PENDING",
                current_step="VECTOR_CLEANUP",
                attempt_count=0,
            )
        )
        session.commit()

    assert get_overview(client, owner).json() == {
        "document_count": 1,
        "ready_document_count": 1,
        "summary_count": 1,
        "chat_session_count": 1,
    }
    assert get_overview(client, other).json() == {
        "document_count": 1,
        "ready_document_count": 1,
        "summary_count": 1,
        "chat_session_count": 1,
    }


def test_dashboard_does_not_count_deleted_document_relations(
    client: TestClient,
    dashboard_session_factory: sessionmaker[Session],
) -> None:
    with dashboard_session_factory() as session:
        user = add_user(session, user_id=1, username="owner")
        document = add_document(
            session,
            document_id=1,
            user_id=user.id,
            status="READY",
        )
        add_summary(session, document_id=document.id, summary_type="SHORT")
        add_chat_session(session, document_id=document.id, title="Deleted session")
        session.flush()
        session.delete(document)
        session.commit()

    assert get_overview(client, user).json() == {
        "document_count": 0,
        "ready_document_count": 0,
        "summary_count": 0,
        "chat_session_count": 0,
    }
