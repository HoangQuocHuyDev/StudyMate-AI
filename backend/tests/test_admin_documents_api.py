"""Isolated API tests for administrator document metadata access."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

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
    func,
    select,
)
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token
from app.db.session import get_db
from app.main import app
from app.models.document import Document
from app.models.document_deletion_job import DocumentDeletionJob
from app.models.user import User


UTC = timezone.utc


@pytest.fixture
def admin_documents_session_factory(
    client: TestClient,
) -> Iterator[sessionmaker[Session]]:
    """Use SQLite only; this fixture cannot connect to a real PostgreSQL DB."""

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
    Document.__table__.to_metadata(metadata)
    DocumentDeletionJob.__table__.to_metadata(metadata)
    metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

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
) -> User:
    user = User(
        id=user_id,
        full_name=f"Người dùng {user_id}",
        username=username,
        password_hash=f"private-hash-{user_id}",
        role=role,
        is_active=True,
        token_version=0,
        created_at=datetime(2026, 10, 1, tzinfo=UTC),
    )
    session.add(user)
    session.flush()
    return user


def add_document(
    session: Session,
    *,
    document_id: int,
    user_id: int,
    title: str | None = None,
    original_filename: str | None = None,
    file_type: str = "PDF",
    status: str = "READY",
    rag_status: str = "READY",
    created_at: datetime | None = None,
) -> Document:
    timestamp = created_at or datetime(2026, 10, 15, tzinfo=UTC)
    mime_type = (
        "application/pdf"
        if file_type == "PDF"
        else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    document = Document(
        id=document_id,
        user_id=user_id,
        title=title or f"Tài liệu {document_id}",
        original_filename=original_filename or f"document-{document_id}.{file_type.lower()}",
        storage_key=f"users/{user_id}/private-storage-{document_id}",
        file_type=file_type,
        mime_type=mime_type,
        file_size=1000 + document_id,
        status=status,
        rag_status=rag_status,
        created_at=timestamp,
        updated_at=timestamp,
        character_count=500,
        page_count=2 if file_type == "PDF" else None,
        processed_at=timestamp if status == "READY" else None,
        indexed_at=timestamp if rag_status == "READY" else None,
    )
    session.add(document)
    session.flush()
    return document


def add_tombstone(
    session: Session,
    *,
    job_id: int,
    document_id: int,
    user_id: int,
) -> None:
    session.add(
        DocumentDeletionJob(
            id=job_id,
            document_id=document_id,
            user_id=user_id,
            storage_key=f"users/{user_id}/private-storage-{document_id}",
            status="PENDING",
            current_step="VECTOR_CLEANUP",
            attempt_count=0,
            created_at=datetime(2026, 10, 15, tzinfo=UTC),
            updated_at=datetime(2026, 10, 15, tzinfo=UTC),
        )
    )
    session.flush()


def auth_header(user: User) -> dict[str, str]:
    token = create_access_token(user.id, user.token_version)
    return {"Authorization": f"Bearer {token}"}


def test_admin_documents_requires_authentication_and_admin_role(
    client: TestClient,
    admin_documents_session_factory: sessionmaker[Session],
) -> None:
    with admin_documents_session_factory() as session:
        standard = add_user(session, user_id=1, username="standard")
        admin = add_user(session, user_id=2, username="admin", role="ADMIN")
        add_document(session, document_id=1, user_id=standard.id)
        session.commit()

    for path in ("/admin/documents", "/admin/documents/1"):
        assert client.get(path).status_code == 401
        assert client.get(
            path,
            headers={"Authorization": "Bearer invalid"},
        ).status_code == 401
        assert client.get(path, headers=auth_header(standard)).status_code == 403
        assert client.get(path, headers=auth_header(admin)).status_code == 200


def test_admin_lists_documents_across_owners_with_stable_pagination(
    client: TestClient,
    admin_documents_session_factory: sessionmaker[Session],
) -> None:
    base = datetime(2026, 10, 15, tzinfo=UTC)
    with admin_documents_session_factory() as session:
        admin = add_user(session, user_id=1, username="admin", role="ADMIN")
        first_owner = add_user(session, user_id=2, username="student_a")
        second_owner = add_user(session, user_id=3, username="student_b")
        add_document(
            session,
            document_id=10,
            user_id=first_owner.id,
            created_at=base - timedelta(days=1),
        )
        add_document(session, document_id=11, user_id=first_owner.id, created_at=base)
        add_document(session, document_id=12, user_id=second_owner.id, created_at=base)
        session.commit()

    first_page = client.get(
        "/admin/documents?limit=2&offset=0",
        headers=auth_header(admin),
    )
    assert first_page.status_code == 200
    assert first_page.json()["total"] == 3
    assert [item["id"] for item in first_page.json()["items"]] == [12, 11]
    assert [item["owner"]["username"] for item in first_page.json()["items"]] == [
        "student_b",
        "student_a",
    ]

    second_page = client.get(
        "/admin/documents?limit=2&offset=2",
        headers=auth_header(admin),
    ).json()
    assert [item["id"] for item in second_page["items"]] == [10]


def test_admin_document_searches_title_and_filename_case_insensitively(
    client: TestClient,
    admin_documents_session_factory: sessionmaker[Session],
) -> None:
    with admin_documents_session_factory() as session:
        admin = add_user(session, user_id=1, username="admin", role="ADMIN")
        owner = add_user(session, user_id=2, username="owner")
        add_document(
            session,
            document_id=1,
            user_id=owner.id,
            title="Giáo trình Python",
            original_filename="course.pdf",
        )
        add_document(
            session,
            document_id=2,
            user_id=owner.id,
            title="Machine Learning",
            original_filename="BAI-GIANG-AI.DOCX",
            file_type="DOCX",
        )
        session.commit()

    by_title = client.get(
        "/admin/documents",
        params={"search": "python"},
        headers=auth_header(admin),
    ).json()
    assert [item["id"] for item in by_title["items"]] == [1]

    by_filename = client.get(
        "/admin/documents",
        params={"search": "bai-giang-ai"},
        headers=auth_header(admin),
    ).json()
    assert [item["id"] for item in by_filename["items"]] == [2]


@pytest.mark.parametrize(
    ("search", "document_id"),
    [("%", 1), ("_", 2), ("\\", 3), (".", 4)],
)
def test_admin_document_search_treats_special_characters_as_literals(
    client: TestClient,
    admin_documents_session_factory: sessionmaker[Session],
    search: str,
    document_id: int,
) -> None:
    with admin_documents_session_factory() as session:
        admin = add_user(session, user_id=1, username="admin", role="ADMIN")
        owner = add_user(session, user_id=2, username="owner")
        values = ("literal%name", "literal_name", r"literal\name", "literal.name")
        for index, value in enumerate(values, start=1):
            add_document(
                session,
                document_id=index,
                user_id=owner.id,
                title=value,
                original_filename=f"safe-{index}-file",
            )
        session.commit()

    payload = client.get(
        "/admin/documents",
        params={"search": search},
        headers=auth_header(admin),
    ).json()
    assert [item["id"] for item in payload["items"]] == [document_id]


def test_admin_document_filters_file_and_processing_states(
    client: TestClient,
    admin_documents_session_factory: sessionmaker[Session],
) -> None:
    with admin_documents_session_factory() as session:
        admin = add_user(session, user_id=1, username="admin", role="ADMIN")
        owner = add_user(session, user_id=2, username="owner")
        add_document(
            session,
            document_id=1,
            user_id=owner.id,
            file_type="PDF",
            status="READY",
            rag_status="READY",
        )
        add_document(
            session,
            document_id=2,
            user_id=owner.id,
            file_type="DOCX",
            status="PROCESSING",
            rag_status="PENDING",
        )
        add_document(
            session,
            document_id=3,
            user_id=owner.id,
            file_type="PDF",
            status="FAILED",
            rag_status="FAILED",
        )
        session.commit()

    filtered = client.get(
        "/admin/documents",
        params={
            "file_type": "DOCX",
            "status": "PROCESSING",
            "rag_status": "PENDING",
        },
        headers=auth_header(admin),
    )
    assert filtered.status_code == 200
    assert [item["id"] for item in filtered.json()["items"]] == [2]


def test_admin_documents_excludes_tombstones_and_missing_detail_is_404(
    client: TestClient,
    admin_documents_session_factory: sessionmaker[Session],
) -> None:
    with admin_documents_session_factory() as session:
        admin = add_user(session, user_id=1, username="admin", role="ADMIN")
        owner = add_user(session, user_id=2, username="owner")
        add_document(session, document_id=1, user_id=owner.id)
        add_document(session, document_id=2, user_id=owner.id)
        add_tombstone(session, job_id=1, document_id=2, user_id=owner.id)
        session.commit()

    listing = client.get("/admin/documents", headers=auth_header(admin))
    assert [item["id"] for item in listing.json()["items"]] == [1]
    assert client.get(
        "/admin/documents/2",
        headers=auth_header(admin),
    ).status_code == 404
    assert client.get(
        "/admin/documents/999",
        headers=auth_header(admin),
    ).status_code == 404


def test_admin_document_detail_returns_metadata_without_sensitive_fields(
    client: TestClient,
    admin_documents_session_factory: sessionmaker[Session],
) -> None:
    with admin_documents_session_factory() as session:
        admin = add_user(session, user_id=1, username="admin", role="ADMIN")
        owner = add_user(session, user_id=2, username="owner")
        add_document(session, document_id=1, user_id=owner.id)
        session.commit()

    response = client.get("/admin/documents/1", headers=auth_header(admin))
    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {
        "id",
        "title",
        "original_filename",
        "file_type",
        "file_size",
        "status",
        "rag_status",
        "owner",
        "created_at",
        "processed_at",
        "indexed_at",
        "mime_type",
        "page_count",
        "character_count",
        "updated_at",
    }
    assert set(payload["owner"]) == {"id", "username", "full_name"}
    serialized = response.text.lower()
    for forbidden in (
        "storage_key",
        "private-storage",
        "password_hash",
        "token_version",
        "content",
        "embedding",
    ):
        assert forbidden not in serialized


def test_admin_document_gets_do_not_modify_data_and_user_api_stays_owner_scoped(
    client: TestClient,
    admin_documents_session_factory: sessionmaker[Session],
) -> None:
    with admin_documents_session_factory() as session:
        admin = add_user(session, user_id=1, username="admin", role="ADMIN")
        first_owner = add_user(session, user_id=2, username="first")
        second_owner = add_user(session, user_id=3, username="second")
        first = add_document(session, document_id=1, user_id=first_owner.id)
        add_document(session, document_id=2, user_id=second_owner.id)
        original_storage_key = first.storage_key
        session.commit()

    assert client.get("/admin/documents", headers=auth_header(admin)).status_code == 200
    assert client.get("/admin/documents/1", headers=auth_header(admin)).status_code == 200

    owner_payload = client.get(
        "/documents?page=1&page_size=100",
        headers=auth_header(first_owner),
    ).json()
    assert [item["id"] for item in owner_payload["items"]] == [1]

    with admin_documents_session_factory() as session:
        assert session.scalar(select(func.count(Document.id))) == 2
        assert session.get(Document, 1).storage_key == original_storage_key


@pytest.mark.parametrize(
    "query",
    [
        "limit=0",
        "limit=101",
        "offset=-1",
        "file_type=TXT",
        "status=DELETED",
        "rag_status=UNKNOWN",
        f"search={'x' * 256}",
    ],
)
def test_admin_documents_rejects_invalid_query_parameters(
    client: TestClient,
    admin_documents_session_factory: sessionmaker[Session],
    query: str,
) -> None:
    with admin_documents_session_factory() as session:
        admin = add_user(session, user_id=1, username="admin", role="ADMIN")
        session.commit()

    assert client.get(
        f"/admin/documents?{query}",
        headers=auth_header(admin),
    ).status_code == 422
