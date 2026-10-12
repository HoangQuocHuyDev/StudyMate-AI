"""Unit tests for private filesystem document storage."""

from __future__ import annotations

import io
import os
import subprocess
from pathlib import Path

import pytest

from app.services.file_storage import (
    EmptyFileError,
    FileAlreadyExistsError,
    FileSizeLimitExceededError,
    FileStorage,
    InvalidStorageKeyError,
    StorageIOError,
)


@pytest.fixture
def storage(tmp_path: Path) -> FileStorage:
    return FileStorage(tmp_path / "documents", max_file_size=1024, chunk_size=8)


def stored_path(root: Path, storage_key: str) -> Path:
    return root.joinpath(*storage_key.split("/"))


def assert_no_temporary_files(root: Path) -> None:
    assert not list(root.rglob(".upload-*.tmp"))


def test_save_valid_file(storage: FileStorage, tmp_path: Path) -> None:
    result = storage.save(io.BytesIO(b"study material"), user_id=12)

    path = stored_path(tmp_path / "documents", result.storage_key)
    assert result.size == 14
    assert path.read_bytes() == b"study material"
    assert result.storage_key.startswith("users/12/")


def test_save_stream_larger_than_one_chunk(
    storage: FileStorage,
    tmp_path: Path,
) -> None:
    content = b"chunked-content-is-larger-than-eight-bytes"

    result = storage.save(io.BytesIO(content), user_id=5)

    assert result.size == len(content)
    assert stored_path(tmp_path / "documents", result.storage_key).read_bytes() == content


def test_empty_file_is_rejected(storage: FileStorage, tmp_path: Path) -> None:
    with pytest.raises(EmptyFileError):
        storage.save(io.BytesIO(b""), user_id=1)

    assert_no_temporary_files(tmp_path / "documents")


def test_oversized_file_is_rejected(storage: FileStorage, tmp_path: Path) -> None:
    with pytest.raises(FileSizeLimitExceededError):
        storage.save(io.BytesIO(b"x" * 1025), user_id=1)

    assert_no_temporary_files(tmp_path / "documents")


def test_stream_error_leaves_no_temporary_file(
    storage: FileStorage,
    tmp_path: Path,
) -> None:
    class FailingStream:
        calls = 0

        def read(self, size: int) -> bytes:
            self.calls += 1
            if self.calls == 1:
                return b"partial"
            raise OSError("simulated stream failure")

    with pytest.raises(StorageIOError):
        storage.save(FailingStream(), user_id=1)  # type: ignore[arg-type]

    assert_no_temporary_files(tmp_path / "documents")
    assert not [
        path
        for path in (tmp_path / "documents").rglob("*")
        if path.is_file()
    ]


def test_generated_keys_are_unique(storage: FileStorage) -> None:
    first = storage.generate_storage_key(3)
    second = storage.generate_storage_key(3)

    assert first != second
    assert first.startswith("users/3/")
    assert second.startswith("users/3/")


@pytest.mark.parametrize("storage_key", ["../outside", "users/1/../../outside"])
def test_delete_rejects_path_traversal(
    storage: FileStorage,
    storage_key: str,
) -> None:
    with pytest.raises(InvalidStorageKeyError):
        storage.delete(storage_key)


def test_delete_rejects_absolute_path(
    storage: FileStorage,
    tmp_path: Path,
) -> None:
    with pytest.raises(InvalidStorageKeyError):
        storage.delete(str((tmp_path / "outside.bin").resolve()))


def test_delete_rejects_symlink_escape(
    storage: FileStorage,
    tmp_path: Path,
) -> None:
    outside_directory = tmp_path / "outside"
    outside_directory.mkdir()
    outside_file = outside_directory / "outside.bin"
    outside_file.write_bytes(b"must remain")
    link_path = tmp_path / "documents" / "escape"
    try:
        os.symlink(outside_directory, link_path, target_is_directory=True)
    except OSError as exc:
        if os.name != "nt":
            pytest.skip(f"Symbolic links are unavailable: {exc}")
        junction = subprocess.run(
            [
                "cmd",
                "/c",
                "mklink",
                "/J",
                str(link_path),
                str(outside_directory),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if junction.returncode != 0:
            pytest.skip("Symbolic links and Windows junctions are unavailable.")

    with pytest.raises(InvalidStorageKeyError):
        storage.delete("escape/outside.bin")
    assert outside_file.read_bytes() == b"must remain"


def test_delete_valid_file(storage: FileStorage, tmp_path: Path) -> None:
    result = storage.save(io.BytesIO(b"delete me"), user_id=8)
    path = stored_path(tmp_path / "documents", result.storage_key)

    assert storage.delete(result.storage_key) is True
    assert not path.exists()


def test_delete_missing_file_is_idempotent(storage: FileStorage) -> None:
    assert storage.delete("users/8/00000000000000000000000000000000") is False


def test_save_never_overwrites_existing_file(
    storage: FileStorage,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collision_key = "users/9/00000000000000000000000000000000"
    destination = stored_path(tmp_path / "documents", collision_key)
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"existing")
    monkeypatch.setattr(
        storage,
        "generate_storage_key",
        lambda user_id: collision_key,
    )

    with pytest.raises(FileAlreadyExistsError):
        storage.save(io.BytesIO(b"replacement"), user_id=9)

    assert destination.read_bytes() == b"existing"
    assert_no_temporary_files(tmp_path / "documents")


def test_publish_race_does_not_overwrite_destination(
    storage: FileStorage,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collision_key = "users/10/00000000000000000000000000000000"
    destination = stored_path(tmp_path / "documents", collision_key)
    monkeypatch.setattr(
        storage,
        "generate_storage_key",
        lambda user_id: collision_key,
    )

    def competing_publish(
        source: Path,
        target: Path,
        *,
        follow_symlinks: bool,
    ) -> None:
        assert source.exists()
        assert follow_symlinks is False
        target.write_bytes(b"created by another writer")
        raise FileExistsError

    monkeypatch.setattr(os, "link", competing_publish)

    with pytest.raises(FileAlreadyExistsError):
        storage.save(io.BytesIO(b"must not replace"), user_id=10)

    assert destination.read_bytes() == b"created by another writer"
    assert_no_temporary_files(tmp_path / "documents")
