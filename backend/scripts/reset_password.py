"""Safely reset one existing StudyMate AI account password.

This is a manually invoked maintenance CLI. It is intentionally not wired to
FastAPI and never prints passwords, password hashes, tokens, or configuration.
"""

from __future__ import annotations

import argparse
import getpass
import re
import sys
from dataclasses import dataclass
from enum import Enum
from typing import Sequence

from pydantic import ValidationError
from sqlalchemy import select, text, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import EXPECTED_DATABASE
from app.core.security import hash_password
from app.models.user import User
from app.schemas.user import UserRegister


_USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_]{3,30}$")


class PasswordResetStatus(str, Enum):
    """Possible non-error outcomes of a password reset transaction."""

    RESET = "RESET"
    NOT_FOUND = "NOT_FOUND"


@dataclass(frozen=True, slots=True)
class PasswordResetResult:
    """Non-sensitive result returned by the reset transaction."""

    status: PasswordResetStatus
    username: str


class PasswordResetError(RuntimeError):
    """Base class for safe password reset failures."""


class PasswordMismatchError(PasswordResetError):
    """Raised when the two hidden password entries do not match."""


class PasswordPolicyError(PasswordResetError):
    """Raised when the registration password policy rejects a password."""


class PasswordResetConflictError(PasswordResetError):
    """Raised when the guarded update does not affect exactly one account."""


class PasswordResetPersistenceError(PasswordResetError):
    """Raised when the reset cannot be persisted safely."""


class WrongDatabaseError(PasswordResetError):
    """Raised before mutation when the connection targets another database."""


def _configure_utf8_output() -> None:
    """Keep Vietnamese CLI messages usable on legacy Windows consoles."""

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            continue


def validate_username(username: str) -> str:
    """Validate the account identifier without normalizing it silently."""

    if not isinstance(username, str) or _USERNAME_PATTERN.fullmatch(username) is None:
        raise ValueError(
            "Username phải dài 3-30 ký tự và chỉ gồm chữ cái, chữ số hoặc dấu gạch dưới."
        )
    return username


def validate_new_password(
    username: str,
    password: str,
    confirmation: str,
) -> str:
    """Apply exactly the validation policy used by public registration."""

    if password != confirmation:
        raise PasswordMismatchError("Hai lần nhập mật khẩu không khớp.")

    try:
        UserRegister(
            full_name="Password Reset",
            username=username,
            password=password,
            confirm_password=confirmation,
        )
    except ValidationError:
        # Pydantic's raw ValidationError may embed the rejected password input,
        # so it must never cross the CLI boundary or be logged.
        raise PasswordPolicyError(
            "Mật khẩu phải dài 8-128 ký tự và chứa ít nhất một chữ cái, một chữ số."
        ) from None
    return password


def reset_existing_user_password(
    db: Session,
    username: str,
    new_password: str,
    *,
    verify_database: bool = False,
) -> PasswordResetResult:
    """Reset one password and atomically revoke all previously issued JWTs."""

    validated_username = validate_username(username)
    validated_password = validate_new_password(
        validated_username,
        new_password,
        new_password,
    )
    try:
        new_password_hash = hash_password(validated_password)
    except Exception as error:
        raise PasswordResetError("Không thể hash mật khẩu an toàn.") from error

    try:
        with db.begin():
            if verify_database:
                database_name = db.scalar(text("SELECT current_database()"))
                if database_name != EXPECTED_DATABASE:
                    raise WrongDatabaseError(
                        "Kết nối database không đúng studymate_ai_db."
                    )

            account = db.execute(
                select(User.id, User.token_version)
                .where(User.username == validated_username)
                .with_for_update()
            ).one_or_none()
            if account is None:
                return PasswordResetResult(
                    status=PasswordResetStatus.NOT_FOUND,
                    username=validated_username,
                )

            result = db.execute(
                update(User)
                .where(
                    User.id == account.id,
                    User.username == validated_username,
                    User.token_version == account.token_version,
                )
                .values(
                    password_hash=new_password_hash,
                    token_version=User.token_version + 1,
                )
            )
            if result.rowcount != 1:
                raise PasswordResetConflictError(
                    "Tài khoản đã thay đổi đồng thời; không đặt lại mật khẩu."
                )
    except PasswordResetError:
        db.rollback()
        raise
    except SQLAlchemyError as error:
        db.rollback()
        raise PasswordResetPersistenceError(
            "Không thể lưu mật khẩu mới do lỗi database."
        ) from error

    return PasswordResetResult(
        status=PasswordResetStatus.RESET,
        username=validated_username,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Đặt lại mật khẩu cho một tài khoản hiện có trong studymate_ai_db."
        )
    )
    parser.add_argument("username", help="Username chính xác cần đặt lại mật khẩu")
    return parser


def _confirm_username(username: str) -> bool:
    confirmation = input(
        f"Nhập lại username '{username}' để xác nhận đặt lại mật khẩu: "
    )
    return confirmation == username


def _read_new_password(username: str) -> str:
    password = getpass.getpass("Mật khẩu mới: ")
    confirmation = getpass.getpass("Nhập lại mật khẩu mới: ")
    return validate_new_password(username, password, confirmation)


def _run_reset(username: str, new_password: str) -> PasswordResetResult:
    # Lazy import ensures inspection and tests never open a production database
    # connection. Settings validate the configured target before SQLAlchemy can
    # connect.
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        return reset_existing_user_password(
            db,
            username,
            new_password,
            verify_database=True,
        )


def main(argv: Sequence[str] | None = None) -> int:
    """Parse, confirm, collect secrets safely, and execute one reset."""

    _configure_utf8_output()
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        username = validate_username(args.username)
    except ValueError as error:
        parser.error(str(error))

    if not _confirm_username(username):
        print("Đã hủy. Không có tài khoản nào được thay đổi.")
        return 1

    try:
        new_password = _read_new_password(username)
    except PasswordResetError as error:
        print(f"Lỗi: {error}", file=sys.stderr)
        return 2
    except (EOFError, KeyboardInterrupt):
        print("\nĐã hủy. Không có tài khoản nào được thay đổi.")
        return 1

    try:
        result = _run_reset(username, new_password)
    except PasswordResetError as error:
        print(f"Lỗi: {error}", file=sys.stderr)
        return 2
    finally:
        # Python strings cannot be reliably zeroed, but keeping the reference
        # scoped to this operation avoids retaining it beyond the CLI request.
        del new_password

    if result.status is PasswordResetStatus.NOT_FOUND:
        print("Không tìm thấy tài khoản có username đã chỉ định.")
        return 3

    print(
        "Đã đặt lại mật khẩu thành công. Toàn bộ access token cũ đã bị thu hồi."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
