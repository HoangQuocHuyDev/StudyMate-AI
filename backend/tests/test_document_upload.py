"""Isolated API tests for authenticated document uploads."""

from __future__ import annotations

import io
from collections.abc import Callable, Iterator
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from app.main import app
from app.routers.documents import get_file_storage
from app.services.file_storage import FileStorage, StorageIOError


def make_pdf() -> bytes:
    return b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\nstartxref\n0\n%%EOF\n"


def make_docx(*, include_bomb: bool = False) -> bytes:
    output = io.BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            "<Types xmlns='http://schemas.openxmlformats.org/package/2006/content-types'/>",
        )
        archive.writestr(
            "_rels/.rels",
            "<Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'/>",
        )
        archive.writestr(
            "word/document.xml",
            "<w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'/>",
        )
        if include_bomb:
            archive.writestr("word/highly-compressed.bin", b"A" * 1_000_000)
    return output.getvalue()


@pytest.fixture
def upload_storage(tmp_path: Path) -> Iterator[tuple[FileStorage, Path]]:
    root = tmp_path / "documents"
    storage = FileStorage(root, max_file_size=256 * 1024, chunk_size=128)
    app.dependency_overrides[get_file_storage] = lambda: storage
    yield storage, root
    app.dependency_overrides.pop(get_file_storage, None)


def authorization_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def stored_files(root: Path) -> list[Path]:
    return [path for path in root.rglob("*") if path.is_file()]


@pytest.mark.parametrize(
    ("filename", "content", "client_mime", "expected_type", "expected_mime"),
    [
        ("lecture.pdf", make_pdf(), "application/pdf", "PDF", "application/pdf"),
        (
            "notes.docx",
            make_docx(),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "DOCX",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
    ],
)
def test_upload_supported_document(
    client: TestClient,
    override_db: Callable,
    fake_session_factory: type,
    active_user: object,
    access_token: str,
    upload_storage: tuple[FileStorage, Path],
    filename: str,
    content: bytes,
    client_mime: str,
    expected_type: str,
    expected_mime: str,
) -> None:
    session = fake_session_factory(get_result=active_user)
    override_db(session)

    response = client.post(
        "/documents/upload",
        headers=authorization_header(access_token),
        files={"file": (filename, content, client_mime)},
        data={"title": "Tài liệu kiểm thử"},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload == {
        "id": 100,
        "title": "Tài liệu kiểm thử",
        "original_filename": filename,
        "file_type": expected_type,
        "mime_type": expected_mime,
        "file_size": len(content),
        "status": "UPLOADED",
        "created_at": session.added.created_at.isoformat().replace("+00:00", "Z"),
    }
    assert "storage_key" not in payload
    assert "user_id" not in payload
    assert session.added.user_id == active_user.id
    assert session.added.file_size == len(content)
    assert session.committed is True
    assert len(stored_files(upload_storage[1])) == 1


def test_upload_requires_jwt(
    client: TestClient,
    upload_storage: tuple[FileStorage, Path],
) -> None:
    response = client.post(
        "/documents/upload",
        files={"file": ("notes.pdf", make_pdf(), "application/pdf")},
    )

    assert response.status_code == 401
    assert not stored_files(upload_storage[1])


def test_upload_rejects_invalid_jwt(
    client: TestClient,
    upload_storage: tuple[FileStorage, Path],
) -> None:
    response = client.post(
        "/documents/upload",
        headers=authorization_header("invalid-token"),
        files={"file": ("notes.pdf", make_pdf(), "application/pdf")},
    )

    assert response.status_code == 401
    assert not stored_files(upload_storage[1])


def test_upload_requires_file(
    client: TestClient,
    override_db: Callable,
    fake_session_factory: type,
    active_user: object,
    access_token: str,
    upload_storage: tuple[FileStorage, Path],
) -> None:
    override_db(fake_session_factory(get_result=active_user))

    response = client.post(
        "/documents/upload",
        headers=authorization_header(access_token),
        data={"title": "Thiếu file"},
    )

    assert response.status_code == 422
    assert not stored_files(upload_storage[1])


def test_upload_rejects_unsupported_extension(
    client: TestClient,
    override_db: Callable,
    fake_session_factory: type,
    active_user: object,
    access_token: str,
    upload_storage: tuple[FileStorage, Path],
) -> None:
    override_db(fake_session_factory(get_result=active_user))

    response = client.post(
        "/documents/upload",
        headers=authorization_header(access_token),
        files={"file": ("malware.exe", b"not executable", "text/plain")},
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "Chỉ hỗ trợ tải lên tệp PDF hoặc DOCX hợp lệ."
    }
    assert not stored_files(upload_storage[1])


def test_upload_rejects_new_txt_document(
    client: TestClient,
    override_db: Callable,
    fake_session_factory: type,
    active_user: object,
    access_token: str,
    upload_storage: tuple[FileStorage, Path],
) -> None:
    override_db(fake_session_factory(get_result=active_user))

    response = client.post(
        "/documents/upload",
        headers=authorization_header(access_token),
        files={"file": ("notes.txt", b"valid UTF-8 text", "text/plain")},
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "Chỉ hỗ trợ tải lên tệp PDF hoặc DOCX hợp lệ."
    }
    assert not stored_files(upload_storage[1])


@pytest.mark.parametrize(
    ("filename", "content", "wrong_mime"),
    [
        ("lecture.pdf", make_pdf(), "text/plain"),
        ("notes.docx", make_docx(), "application/octet-stream"),
    ],
)
def test_upload_rejects_mismatched_mime_type(
    client: TestClient,
    override_db: Callable,
    fake_session_factory: type,
    active_user: object,
    access_token: str,
    upload_storage: tuple[FileStorage, Path],
    filename: str,
    content: bytes,
    wrong_mime: str,
) -> None:
    override_db(fake_session_factory(get_result=active_user))

    response = client.post(
        "/documents/upload",
        headers=authorization_header(access_token),
        files={"file": (filename, content, wrong_mime)},
    )

    assert response.status_code == 400
    assert not stored_files(upload_storage[1])


def test_upload_rejects_empty_file(
    client: TestClient,
    override_db: Callable,
    fake_session_factory: type,
    active_user: object,
    access_token: str,
    upload_storage: tuple[FileStorage, Path],
) -> None:
    override_db(fake_session_factory(get_result=active_user))

    response = client.post(
        "/documents/upload",
        headers=authorization_header(access_token),
        files={"file": ("empty.pdf", b"", "application/pdf")},
    )

    assert response.status_code == 400
    assert not stored_files(upload_storage[1])


def test_upload_rejects_oversized_file(
    client: TestClient,
    override_db: Callable,
    fake_session_factory: type,
    active_user: object,
    access_token: str,
    upload_storage: tuple[FileStorage, Path],
) -> None:
    _, root = upload_storage
    override_db(fake_session_factory(get_result=active_user))

    response = client.post(
        "/documents/upload",
        headers=authorization_header(access_token),
        files={
            "file": (
                "large.pdf",
                b"x" * (256 * 1024 + 1),
                "application/pdf",
            )
        },
    )

    assert response.status_code == 413
    assert not stored_files(root)


@pytest.mark.parametrize(
    ("filename", "content", "client_mime"),
    [
        ("fake.pdf", b"This is not a PDF", "application/pdf"),
        (
            "fake.docx",
            b"This is not a ZIP archive",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
    ],
)
def test_upload_rejects_spoofed_content(
    client: TestClient,
    override_db: Callable,
    fake_session_factory: type,
    active_user: object,
    access_token: str,
    upload_storage: tuple[FileStorage, Path],
    filename: str,
    content: bytes,
    client_mime: str,
) -> None:
    override_db(fake_session_factory(get_result=active_user))

    response = client.post(
        "/documents/upload",
        headers=authorization_header(access_token),
        files={"file": (filename, content, client_mime)},
    )

    assert response.status_code == 400
    assert not stored_files(upload_storage[1])


@pytest.mark.parametrize(
    ("filename", "title", "expected_status"),
    [
        ("", None, 422),
        (f"{'a' * 252}.pdf", None, 400),
        ("notes.pdf", "   ", 400),
        ("notes.pdf", "a" * 256, 400),
    ],
)
def test_upload_rejects_invalid_filename_or_title(
    client: TestClient,
    override_db: Callable,
    fake_session_factory: type,
    active_user: object,
    access_token: str,
    upload_storage: tuple[FileStorage, Path],
    filename: str,
    title: str | None,
    expected_status: int,
) -> None:
    override_db(fake_session_factory(get_result=active_user))
    data = {} if title is None else {"title": title}

    response = client.post(
        "/documents/upload",
        headers=authorization_header(access_token),
        files={"file": (filename, make_pdf(), "application/pdf")},
        data=data,
    )

    assert response.status_code == expected_status
    assert not stored_files(upload_storage[1])


def test_upload_rejects_inactive_account(
    client: TestClient,
    override_db: Callable,
    fake_session_factory: type,
    user_factory: Callable,
    access_token: str,
    upload_storage: tuple[FileStorage, Path],
) -> None:
    inactive_user = user_factory(is_active=False)
    override_db(fake_session_factory(get_result=inactive_user))

    response = client.post(
        "/documents/upload",
        headers=authorization_header(access_token),
        files={"file": ("notes.pdf", make_pdf(), "application/pdf")},
    )

    assert response.status_code == 401
    assert not stored_files(upload_storage[1])


def test_upload_normalizes_filename_and_ignores_client_user_id(
    client: TestClient,
    override_db: Callable,
    fake_session_factory: type,
    active_user: object,
    access_token: str,
    upload_storage: tuple[FileStorage, Path],
) -> None:
    session = fake_session_factory(get_result=active_user)
    override_db(session)

    response = client.post(
        "/documents/upload",
        headers=authorization_header(access_token),
        files={
            "file": (
                r"C:\fakepath\bai-giang.pdf",
                make_pdf(),
                "application/pdf",
            )
        },
        data={"user_id": "999999"},
    )

    assert response.status_code == 201
    assert response.json()["original_filename"] == "bai-giang.pdf"
    assert response.json()["title"] == "bai-giang"
    assert response.json()["mime_type"] == "application/pdf"
    assert session.added.user_id == active_user.id
    assert session.added.user_id != 999999


def test_database_error_rolls_back_and_removes_file(
    client: TestClient,
    override_db: Callable,
    fake_session_factory: type,
    active_user: object,
    access_token: str,
    upload_storage: tuple[FileStorage, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = fake_session_factory(get_result=active_user)

    def fail_flush() -> None:
        raise SQLAlchemyError("simulated database failure")

    monkeypatch.setattr(session, "flush", fail_flush)
    override_db(session)

    response = client.post(
        "/documents/upload",
        headers=authorization_header(access_token),
        files={"file": ("notes.pdf", make_pdf(), "application/pdf")},
    )

    assert response.status_code == 500
    assert session.rollback_called is True
    assert not stored_files(upload_storage[1])


def test_cleanup_failure_log_redacts_sensitive_upload_details(
    client: TestClient,
    override_db: Callable,
    fake_session_factory: type,
    active_user: object,
    access_token: str,
    upload_storage: tuple[FileStorage, Path],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    session = fake_session_factory(get_result=active_user)
    sensitive_exception = "sensitive-delete-error-at-C:/private/documents"
    deleted_keys: list[str] = []

    def fail_flush() -> None:
        raise SQLAlchemyError("simulated database failure")

    def fail_delete(storage_key: str) -> bool:
        deleted_keys.append(storage_key)
        raise StorageIOError(sensitive_exception)

    monkeypatch.setattr(session, "flush", fail_flush)
    monkeypatch.setattr(upload_storage[0], "delete", fail_delete)
    override_db(session)
    caplog.set_level("ERROR", logger="app.services.document_service")

    response = client.post(
        "/documents/upload",
        headers=authorization_header(access_token),
        files={"file": ("notes.pdf", make_pdf(), "application/pdf")},
    )

    assert response.status_code == 500
    assert response.json() == {
        "detail": "Không thể lưu tài liệu lúc này."
    }
    assert session.rollback_called is True
    assert len(deleted_keys) == 1
    assert "event=document_upload_cleanup_failed" in caplog.text
    assert deleted_keys[0] not in caplog.text
    assert str(active_user.id) not in "\n".join(
        record.getMessage() for record in caplog.records
    )
    assert str(upload_storage[1]) not in caplog.text
    assert sensitive_exception not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


def test_upload_rejects_high_compression_docx(
    client: TestClient,
    override_db: Callable,
    fake_session_factory: type,
    active_user: object,
    access_token: str,
    upload_storage: tuple[FileStorage, Path],
) -> None:
    override_db(fake_session_factory(get_result=active_user))

    response = client.post(
        "/documents/upload",
        headers=authorization_header(access_token),
        files={
            "file": (
                "bomb.docx",
                make_docx(include_bomb=True),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )

    assert response.status_code == 400
    assert not stored_files(upload_storage[1])
