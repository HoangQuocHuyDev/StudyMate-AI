"""Private, filesystem-backed storage for uploaded document bytes."""

from __future__ import annotations

import os
import re
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import BinaryIO
from uuid import uuid4

from app.core.config import get_settings


DEFAULT_CHUNK_SIZE = 64 * 1024
_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class FileStorageError(Exception):
    """Base error for safe storage operations."""


class InvalidStorageKeyError(FileStorageError):
    """Raised when a storage key is unsafe or malformed."""


class EmptyFileError(FileStorageError):
    """Raised when a stream contains no bytes."""


class FileSizeLimitExceededError(FileStorageError):
    """Raised when a stream exceeds its configured byte limit."""


class FileAlreadyExistsError(FileStorageError):
    """Raised when a generated storage destination already exists."""


class StorageIOError(FileStorageError):
    """Raised when a filesystem or stream operation fails."""


@dataclass(frozen=True, slots=True)
class StoredFile:
    """Public result of a successful storage operation."""

    storage_key: str
    size: int


class FileStorage:
    """Store private document bytes below one normalized root directory."""

    def __init__(
        self,
        root: str | Path,
        *,
        max_file_size: int,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
    ) -> None:
        if max_file_size <= 0:
            raise ValueError("max_file_size must be greater than zero.")
        if chunk_size <= 0:
            raise ValueError("chunk_size must be greater than zero.")

        normalized_root = Path(root).expanduser().resolve(strict=False)
        try:
            normalized_root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise StorageIOError("Could not initialize file storage.") from exc
        if not normalized_root.is_dir():
            raise StorageIOError("Could not initialize file storage.")

        self._root = normalized_root
        self._max_file_size = max_file_size
        self._chunk_size = chunk_size

    @classmethod
    def from_settings(cls) -> FileStorage:
        """Create storage using validated application configuration."""

        settings = get_settings()
        return cls(
            settings.storage_root,
            max_file_size=settings.max_upload_size_bytes,
        )

    def generate_storage_key(self, user_id: int) -> str:
        """Generate an opaque relative key for an internally verified user ID."""

        if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
            raise InvalidStorageKeyError("Invalid internal user identifier.")
        return f"users/{user_id}/{uuid4().hex}"

    @property
    def max_file_size(self) -> int:
        """Return the configured per-file byte limit."""

        return self._max_file_size

    def save(self, stream: BinaryIO, *, user_id: int) -> StoredFile:
        """Write a binary stream in chunks and atomically publish the result."""

        storage_key = self.generate_storage_key(user_id)
        destination = self._path_for_key(storage_key)
        self._prepare_parent(destination.parent)

        if self._exists_without_following(destination):
            raise FileAlreadyExistsError("Storage destination already exists.")

        temporary_path: Path | None = None
        published = False
        try:
            file_descriptor, temporary_name = tempfile.mkstemp(
                prefix=".upload-",
                suffix=".tmp",
                dir=destination.parent,
            )
            temporary_path = Path(temporary_name)
            size = self._write_stream(file_descriptor, stream)

            self._assert_safe_existing_path(destination.parent)
            try:
                os.link(
                    temporary_path,
                    destination,
                    follow_symlinks=False,
                )
            except FileExistsError as exc:
                raise FileAlreadyExistsError(
                    "Storage destination already exists."
                ) from exc
            published = True
            temporary_path.unlink()
            temporary_path = None
            return StoredFile(storage_key=storage_key, size=size)
        except FileStorageError:
            if published:
                self._safe_unlink(destination)
            self._safe_unlink(temporary_path)
            raise
        except (OSError, TypeError, ValueError) as exc:
            if published:
                self._safe_unlink(destination)
            self._safe_unlink(temporary_path)
            raise StorageIOError("Could not store file.") from exc

    def delete(self, storage_key: str) -> bool:
        """Delete one regular file by internal key; missing files are successful."""

        destination = self._path_for_key(storage_key)
        self._assert_safe_existing_path(destination)

        try:
            file_status = destination.lstat()
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise StorageIOError("Could not inspect stored file.") from exc

        if stat.S_ISLNK(file_status.st_mode) or not stat.S_ISREG(
            file_status.st_mode
        ):
            raise InvalidStorageKeyError("Storage key does not identify a file.")

        try:
            destination.unlink()
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise StorageIOError("Could not delete stored file.") from exc
        return True

    def _write_stream(self, file_descriptor: int, stream: BinaryIO) -> int:
        size = 0
        try:
            with os.fdopen(file_descriptor, "wb") as target:
                while True:
                    try:
                        chunk = stream.read(self._chunk_size)
                    except Exception as exc:
                        raise StorageIOError(
                            "Could not read the file stream."
                        ) from exc
                    if not chunk:
                        break
                    if not isinstance(chunk, (bytes, bytearray, memoryview)):
                        raise StorageIOError("Upload stream must contain bytes.")
                    size += len(chunk)
                    if size > self._max_file_size:
                        raise FileSizeLimitExceededError(
                            "File exceeds the configured size limit."
                        )
                    target.write(chunk)

                if size == 0:
                    raise EmptyFileError("Empty files are not allowed.")
                target.flush()
                os.fsync(target.fileno())
        except FileStorageError:
            raise
        except (OSError, TypeError, ValueError) as exc:
            raise StorageIOError("Could not read or write the file stream.") from exc
        return size

    def _path_for_key(self, storage_key: str) -> Path:
        parts = self._validate_storage_key(storage_key)
        candidate = self._root.joinpath(*parts)
        self._assert_contained(candidate)
        return candidate

    @staticmethod
    def _validate_storage_key(storage_key: str) -> tuple[str, ...]:
        if not isinstance(storage_key, str) or not storage_key:
            raise InvalidStorageKeyError("Invalid storage key.")
        if "\x00" in storage_key or "\\" in storage_key:
            raise InvalidStorageKeyError("Invalid storage key.")
        if PurePosixPath(storage_key).is_absolute() or PureWindowsPath(
            storage_key
        ).is_absolute():
            raise InvalidStorageKeyError("Absolute storage keys are not allowed.")

        parts = tuple(storage_key.split("/"))
        if any(
            part in {"", ".", ".."} or _SAFE_SEGMENT.fullmatch(part) is None
            for part in parts
        ):
            raise InvalidStorageKeyError("Invalid storage key.")
        return parts

    def _assert_contained(self, path: Path) -> None:
        try:
            path.resolve(strict=False).relative_to(self._root)
        except (OSError, ValueError) as exc:
            raise InvalidStorageKeyError(
                "Storage key escapes the configured root."
            ) from exc

    def _assert_safe_existing_path(self, path: Path) -> None:
        self._assert_contained(path)
        try:
            relative_parts = path.relative_to(self._root).parts
        except ValueError as exc:
            raise InvalidStorageKeyError(
                "Storage key escapes the configured root."
            ) from exc

        current = self._root
        for part in relative_parts:
            current /= part
            try:
                current_status = current.lstat()
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise StorageIOError("Could not inspect storage path.") from exc
            if stat.S_ISLNK(current_status.st_mode):
                raise InvalidStorageKeyError(
                    "Symbolic links are not allowed in storage paths."
                )
        self._assert_contained(path)

    def _prepare_parent(self, parent: Path) -> None:
        self._assert_contained(parent)
        relative_parts = parent.relative_to(self._root).parts
        current = self._root
        for part in relative_parts:
            current /= part
            try:
                current.mkdir()
            except FileExistsError:
                pass
            except OSError as exc:
                raise StorageIOError("Could not prepare storage directory.") from exc

            try:
                current_status = current.lstat()
            except OSError as exc:
                raise StorageIOError("Could not inspect storage directory.") from exc
            if stat.S_ISLNK(current_status.st_mode) or not stat.S_ISDIR(
                current_status.st_mode
            ):
                raise InvalidStorageKeyError("Unsafe storage directory.")
        self._assert_contained(parent)

    @staticmethod
    def _exists_without_following(path: Path) -> bool:
        try:
            path.lstat()
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise StorageIOError("Could not inspect storage destination.") from exc
        return True

    @staticmethod
    def _safe_unlink(path: Path | None) -> None:
        if path is None:
            return
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
