"""Isolated API tests for authenticated document metadata listing."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
)
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token
from app.db.session import get_db
from app.main import app
from app.models.document import Document
from app.models.document_deletion_job import DocumentDeletionJob
from app.models.user import User


def authorization_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def document_session_factory(
    client: TestClient,
) -> Iterator[sessionmaker[Session]]:
    """Use an in-memory SQLite schema without touching PostgreSQL."""

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
        Column("token_version", BigInteger, nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
    )
    Document.__table__.to_metadata(metadata)
    DocumentDeletionJob.__table__.to_metadata(metadata)
    metadata.create_all(engine)
    test_session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )

    def override() -> Iterator[Session]:
        with test_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override
    yield test_session_factory
    app.dependency_overrides.pop(get_db, None)
    engine.dispose()


def add_user(
    session_factory: sessionmaker[Session],
    *,
    user_id: int,
    role: str = "USER",
    is_active: bool = True,
) -> User:
    user = User(
        id=user_id,
        full_name=f"User {user_id}",
        username=f"user_{user_id}",
        password_hash="test-only-hash",
        role=role,
        is_active=is_active,
        created_at=datetime.now(timezone.utc),
    )
    with session_factory() as session:
        session.add(user)
        session.commit()
    return user


def add_document(
    session_factory: sessionmaker[Session],
    *,
    document_id: int,
    user_id: int,
    title: str,
    file_type: str = "PDF",
    created_at: datetime | None = None,
) -> None:
    with session_factory() as session:
        session.add(
            Document(
                id=document_id,
                user_id=user_id,
                title=title,
                original_filename=f"document-{document_id}.{file_type.lower()}",
                storage_key=f"users/{user_id}/{document_id}",
                file_type=file_type,
                mime_type={
                    "PDF": "application/pdf",
                    "DOCX": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                }[file_type],
                file_size=100 + document_id,
                status="UPLOADED",
                created_at=created_at or datetime.now(timezone.utc),
                updated_at=created_at or datetime.now(timezone.utc),
            )
        )
        session.commit()


def get_as_user(client: TestClient, user: User, **params: object):
    return client.get(
        "/documents",
        headers=authorization_header(
            create_access_token(user.id, user.token_version)
        ),
        params=params,
    )


def test_get_documents_succeeds_with_valid_jwt_and_hides_private_fields(
    client: TestClient,
    document_session_factory: sessionmaker[Session],
) -> None:
    user = add_user(document_session_factory, user_id=1)
    add_document(
        document_session_factory,
        document_id=10,
        user_id=user.id,
        title="Giới thiệu trí tuệ nhân tạo",
    )

    response = get_as_user(client, user)

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["title"] == "Giới thiệu trí tuệ nhân tạo"
    assert "storage_key" not in response.json()["items"][0]
    assert "user_id" not in response.json()["items"][0]


def test_get_documents_requires_valid_jwt(
    client: TestClient,
    document_session_factory: sessionmaker[Session],
) -> None:
    assert client.get("/documents").status_code == 401
    assert client.get(
        "/documents",
        headers=authorization_header("invalid-token"),
    ).status_code == 401


def test_get_documents_rejects_inactive_account(
    client: TestClient,
    document_session_factory: sessionmaker[Session],
) -> None:
    inactive_user = add_user(
        document_session_factory,
        user_id=1,
        is_active=False,
    )

    response = get_as_user(client, inactive_user)

    assert response.status_code == 401


def test_get_documents_returns_only_current_users_documents(
    client: TestClient,
    document_session_factory: sessionmaker[Session],
) -> None:
    current_user = add_user(document_session_factory, user_id=1)
    other_user = add_user(document_session_factory, user_id=2)
    add_document(
        document_session_factory,
        document_id=1,
        user_id=current_user.id,
        title="Của tôi",
    )
    add_document(
        document_session_factory,
        document_id=2,
        user_id=other_user.id,
        title="Không thuộc về tôi",
    )

    payload = get_as_user(client, current_user, user_id=other_user.id).json()

    assert payload["total"] == 1
    assert [item["id"] for item in payload["items"]] == [1]


def test_get_documents_returns_empty_page(
    client: TestClient,
    document_session_factory: sessionmaker[Session],
) -> None:
    user = add_user(document_session_factory, user_id=1)

    response = get_as_user(client, user)

    assert response.status_code == 200
    assert response.json() == {
        "items": [],
        "page": 1,
        "page_size": 10,
        "total": 0,
        "total_pages": 0,
    }


def test_get_documents_paginates_and_uses_stable_newest_first_order(
    client: TestClient,
    document_session_factory: sessionmaker[Session],
) -> None:
    user = add_user(document_session_factory, user_id=1)
    base_time = datetime(2026, 10, 12, 10, 0, tzinfo=timezone.utc)
    add_document(
        document_session_factory,
        document_id=1,
        user_id=user.id,
        title="Cũ",
        created_at=base_time - timedelta(days=1),
    )
    add_document(
        document_session_factory,
        document_id=2,
        user_id=user.id,
        title="Mới A",
        created_at=base_time,
    )
    add_document(
        document_session_factory,
        document_id=3,
        user_id=user.id,
        title="Mới B",
        created_at=base_time,
    )

    first_page = get_as_user(client, user, page=1, page_size=2).json()
    second_page = get_as_user(client, user, page=2, page_size=2).json()

    assert [item["id"] for item in first_page["items"]] == [3, 2]
    assert [item["id"] for item in second_page["items"]] == [1]
    assert first_page["total"] == 3
    assert first_page["total_pages"] == 2


@pytest.mark.parametrize(
    ("params", "expected_status"),
    [
        ({"page": 0}, 422),
        ({"page_size": 0}, 422),
        ({"page_size": 101}, 422),
        ({"page": "invalid"}, 422),
        ({"page_size": "invalid"}, 422),
    ],
)
def test_get_documents_rejects_invalid_pagination(
    client: TestClient,
    document_session_factory: sessionmaker[Session],
    params: dict[str, object],
    expected_status: int,
) -> None:
    user = add_user(document_session_factory, user_id=1)

    assert get_as_user(client, user, **params).status_code == expected_status


def test_get_documents_searches_case_insensitively_and_trims_whitespace(
    client: TestClient,
    document_session_factory: sessionmaker[Session],
) -> None:
    user = add_user(document_session_factory, user_id=1)
    add_document(
        document_session_factory,
        document_id=1,
        user_id=user.id,
        title="Nhap MON Tri Tue Nhan Tao",
    )
    add_document(
        document_session_factory,
        document_id=2,
        user_id=user.id,
        title="Kinh tế học",
    )

    payload = get_as_user(client, user, search="  mon tri tue  ").json()

    assert payload["total"] == 1
    assert payload["items"][0]["id"] == 1
    assert get_as_user(client, user, search="   ").json()["total"] == 2


@pytest.mark.parametrize(
    ("search", "matching_id"),
    [("100%", 1), ("bài_tập", 2), (r"C:\\notes", 3)],
)
def test_get_documents_search_treats_like_wildcards_as_literals(
    client: TestClient,
    document_session_factory: sessionmaker[Session],
    search: str,
    matching_id: int,
) -> None:
    user = add_user(document_session_factory, user_id=1)
    titles = [
        "Tiến độ 100%",
        "bài_tập chương 1",
        r"C:\\notes đại số",
        "100 điểm",
    ]
    for document_id, title in enumerate(titles, start=1):
        add_document(
            document_session_factory,
            document_id=document_id,
            user_id=user.id,
            title=title,
        )

    payload = get_as_user(client, user, search=search).json()

    assert payload["total"] == 1
    assert payload["items"][0]["id"] == matching_id


@pytest.mark.parametrize("file_type", ["PDF", "docx"])
def test_get_documents_filters_supported_file_types_case_insensitively(
    client: TestClient,
    document_session_factory: sessionmaker[Session],
    file_type: str,
) -> None:
    user = add_user(document_session_factory, user_id=1)
    for document_id, stored_type in enumerate(("PDF", "DOCX"), start=1):
        add_document(
            document_session_factory,
            document_id=document_id,
            user_id=user.id,
            title=stored_type,
            file_type=stored_type,
        )

    payload = get_as_user(client, user, file_type=file_type).json()

    assert payload["total"] == 1
    assert payload["items"][0]["file_type"] == file_type.upper()


def test_get_documents_rejects_invalid_file_type_and_long_search(
    client: TestClient,
    document_session_factory: sessionmaker[Session],
) -> None:
    user = add_user(document_session_factory, user_id=1)

    assert get_as_user(client, user, file_type="EXE").status_code == 422
    assert get_as_user(client, user, file_type="TXT").status_code == 422
    assert get_as_user(client, user, search="a" * 256).status_code == 422


def test_get_documents_combines_owner_search_type_and_pagination(
    client: TestClient,
    document_session_factory: sessionmaker[Session],
) -> None:
    user = add_user(document_session_factory, user_id=1)
    other_user = add_user(document_session_factory, user_id=2)
    for document_id, owner_id, title, file_type in (
        (1, user.id, "AI căn bản", "PDF"),
        (2, user.id, "AI nâng cao", "PDF"),
        (3, user.id, "AI ghi chú", "DOCX"),
        (4, other_user.id, "AI của người khác", "PDF"),
    ):
        add_document(
            document_session_factory,
            document_id=document_id,
            user_id=owner_id,
            title=title,
            file_type=file_type,
        )

    payload = get_as_user(
        client,
        user,
        search="AI",
        file_type="pdf",
        page=2,
        page_size=1,
    ).json()

    assert payload["total"] == 2
    assert payload["total_pages"] == 2
    assert [item["id"] for item in payload["items"]] == [1]


def test_admin_only_sees_owned_documents(
    client: TestClient,
    document_session_factory: sessionmaker[Session],
) -> None:
    admin = add_user(document_session_factory, user_id=1, role="ADMIN")
    other_user = add_user(document_session_factory, user_id=2)
    add_document(
        document_session_factory,
        document_id=1,
        user_id=admin.id,
        title="Của admin",
    )
    add_document(
        document_session_factory,
        document_id=2,
        user_id=other_user.id,
        title="Của user",
    )

    payload = get_as_user(client, admin).json()

    assert payload["total"] == 1
    assert payload["items"][0]["id"] == 1


def test_get_documents_database_error_returns_safe_500(
    client: TestClient,
    override_db: Callable,
    fake_session_factory: type,
    active_user: User,
    access_token: str,
) -> None:
    session = fake_session_factory(
        get_result=active_user,
        scalar_error=SQLAlchemyError("private database detail"),
    )
    override_db(session)

    response = client.get(
        "/documents",
        headers=authorization_header(access_token),
    )

    assert response.status_code == 500
    assert session.rollback_called is True
    assert "private database detail" not in response.text


def test_openapi_declares_document_list_response(
    client: TestClient,
) -> None:
    operation = client.get("/openapi.json").json()["paths"]["/documents"]["get"]

    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/DocumentListResponse"
    }
