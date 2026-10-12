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
from app.services.file_storage import FileStorage


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
        ("lecture.pdf", make_pdf(), "text/plain", "PDF", "application/pdf"),
        (
            "notes.docx",
            make_docx(),
            "application/octet-stream",
            "DOCX",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
        (
            "ghi-chu.txt",
            "Nội dung học tập UTF-8".encode(),
            "application/octet-stream",
            "TXT",
            "text/plain; charset=utf-8",
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
        files={"file": ("notes.txt", b"valid text", "text/plain")},
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
        files={"file": ("notes.txt", b"valid text", "text/plain")},
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

    assert response.status_code == 415
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
        files={"file": ("empty.txt", b"", "text/plain")},
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
        files={"file": ("large.txt", b"x" * (256 * 1024 + 1), "text/plain")},
    )

    assert response.status_code == 413
    assert not stored_files(root)


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        ("fake.pdf", b"This is not a PDF"),
        ("fake.docx", b"This is not a ZIP archive"),
        ("fake.txt", b"\x00\xff\x00binary"),
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
) -> None:
    override_db(fake_session_factory(get_result=active_user))

    response = client.post(
        "/documents/upload",
        headers=authorization_header(access_token),
        files={"file": (filename, content, "application/octet-stream")},
    )

    assert response.status_code == 400
    assert not stored_files(upload_storage[1])


@pytest.mark.parametrize(
    ("filename", "title", "expected_status"),
    [
        ("", None, 422),
        (f"{'a' * 252}.txt", None, 400),
        ("notes.txt", "   ", 400),
        ("notes.txt", "a" * 256, 400),
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
        files={"file": (filename, b"valid text", "text/plain")},
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
        files={"file": ("notes.txt", b"valid text", "text/plain")},
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
                r"C:\fakepath\ghi-chu.txt",
                "Nội dung".encode(),
                "application/x-client-guess",
            )
        },
        data={"user_id": "999999"},
    )

    assert response.status_code == 201
    assert response.json()["original_filename"] == "ghi-chu.txt"
    assert response.json()["title"] == "ghi-chu"
    assert response.json()["mime_type"] == "text/plain; charset=utf-8"
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
        files={"file": ("notes.txt", b"valid text", "text/plain")},
    )

    assert response.status_code == 500
    assert session.rollback_called is True
    assert not stored_files(upload_storage[1])


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
