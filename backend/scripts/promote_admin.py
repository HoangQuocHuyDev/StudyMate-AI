"""Safely promote one existing StudyMate AI user to the ADMIN role.

Run this module from the backend directory. It deliberately is not exposed
through FastAPI and never handles or displays account credentials.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from enum import Enum
from typing import Sequence

from sqlalchemy import select, text, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import EXPECTED_DATABASE
from app.models.user import User


_USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_]{3,30}$")


class PromotionStatus(str, Enum):
    """Possible non-error outcomes of an administrator promotion."""

    PROMOTED = "PROMOTED"
    ALREADY_ADMIN = "ALREADY_ADMIN"
    NOT_FOUND = "NOT_FOUND"


@dataclass(frozen=True, slots=True)
class PromotionResult:
    """Non-sensitive result returned by the promotion transaction."""

    status: PromotionStatus
    username: str


class AdminPromotionError(RuntimeError):
    """Raised when the requested promotion cannot be completed safely."""


class UnexpectedUserRoleError(AdminPromotionError):
    """Raised when an account contains a role outside USER/ADMIN."""


class PromotionConflictError(AdminPromotionError):
    """Raised when the guarded update does not affect exactly one account."""


class PromotionPersistenceError(AdminPromotionError):
    """Raised when the database operation fails."""


class WrongDatabaseError(AdminPromotionError):
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
            # Captured or already-closed streams do not need reconfiguration.
            continue


def validate_username(username: str) -> str:
    """Validate a username exactly as the public account schema does."""

    if not isinstance(username, str) or _USERNAME_PATTERN.fullmatch(username) is None:
        raise ValueError(
            "Username phải dài 3-30 ký tự và chỉ gồm chữ cái, chữ số hoặc dấu gạch dưới."
        )
    return username


def promote_existing_user(
    db: Session,
    username: str,
    *,
    verify_database: bool = False,
) -> PromotionResult:
    """Atomically promote one existing USER while preserving all other fields.

    ``verify_database`` is enabled by the real CLI. Tests can keep it disabled
    while using an isolated SQLite database that has no ``current_database``
    function.
    """

    validated_username = validate_username(username)

    try:
        with db.begin():
            if verify_database:
                database_name = db.scalar(text("SELECT current_database()"))
                if database_name != EXPECTED_DATABASE:
                    raise WrongDatabaseError(
                        "Kết nối database không đúng studymate_ai_db."
                    )

            account = db.execute(
                select(User.id, User.role)
                .where(User.username == validated_username)
                .with_for_update()
            ).one_or_none()

            if account is None:
                return PromotionResult(
                    status=PromotionStatus.NOT_FOUND,
                    username=validated_username,
                )
            if account.role == "ADMIN":
                return PromotionResult(
                    status=PromotionStatus.ALREADY_ADMIN,
                    username=validated_username,
                )
            if account.role != "USER":
                raise UnexpectedUserRoleError(
                    "Tài khoản có role không hợp lệ; không thực hiện cập nhật."
                )

            result = db.execute(
                update(User)
                .where(
                    User.id == account.id,
                    User.username == validated_username,
                    User.role == "USER",
                )
                .values(role="ADMIN")
            )
            if result.rowcount != 1:
                raise PromotionConflictError(
                    "Tài khoản đã thay đổi đồng thời; không thực hiện nâng quyền."
                )
    except AdminPromotionError:
        db.rollback()
        raise
    except SQLAlchemyError as error:
        db.rollback()
        raise PromotionPersistenceError(
            "Không thể cập nhật role do lỗi database."
        ) from error

    return PromotionResult(
        status=PromotionStatus.PROMOTED,
        username=validated_username,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Nâng quyền một tài khoản USER hiện có lên ADMIN trong "
            "studymate_ai_db."
        )
    )
    parser.add_argument("username", help="Username chính xác cần nâng quyền")
    return parser


def _confirm(username: str) -> bool:
    confirmation = input(
        f"Nhập lại username '{username}' để xác nhận nâng quyền ADMIN: "
    )
    return confirmation == username


def _run_promotion(username: str) -> PromotionResult:
    # Import lazily: importing this module for tests or inspection never opens a
    # production database connection. Settings also validate the configured
    # target before SQLAlchemy can connect.
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        return promote_existing_user(
            db,
            username,
            verify_database=True,
        )


def main(argv: Sequence[str] | None = None) -> int:
    """Parse, confirm, and run one manually initiated promotion."""

    _configure_utf8_output()
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        username = validate_username(args.username)
    except ValueError as error:
        parser.error(str(error))

    if not _confirm(username):
        print("Đã hủy. Không có tài khoản nào được thay đổi.")
        return 1

    try:
        result = _run_promotion(username)
    except AdminPromotionError as error:
        print(f"Lỗi: {error}", file=sys.stderr)
        return 2

    if result.status is PromotionStatus.NOT_FOUND:
        print("Không tìm thấy tài khoản có username đã chỉ định.")
        return 3
    if result.status is PromotionStatus.ALREADY_ADMIN:
        print("Tài khoản đã có role ADMIN; không thực hiện cập nhật.")
        return 0

    print("Đã nâng quyền tài khoản lên ADMIN thành công.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
