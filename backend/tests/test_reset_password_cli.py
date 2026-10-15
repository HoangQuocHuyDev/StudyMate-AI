"""Tests for the manually invoked password reset CLI."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
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
    insert,
    select,
)
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.core.security import verify_password
from scripts import reset_password
from scripts.reset_password import (
    PasswordMismatchError,
    PasswordPolicyError,
    PasswordResetPersistenceError,
    PasswordResetResult,
    PasswordResetStatus,
    reset_existing_user_password,
    validate_new_password,
)


@pytest.fixture
def password_cli_database() -> sessionmaker[Session]:
    """Provide a minimal isolated users table without touching PostgreSQL."""

    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata = MetaData()
    Table(
        "users",
        metadata,
        Column("id", BigInteger, primary_key=True),
        Column("full_name", String(100), nullable=False),
        Column("username", String(30), nullable=False, unique=True),
        Column("password_hash", Text, nullable=False),
        Column("role", String(10), nullable=False),
        Column("is_active", Boolean, nullable=False),
        Column("token_version", Integer, nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
    )
    metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _users_table(session_factory: sessionmaker[Session]) -> Table:
    return Table(
        "users",
        MetaData(),
        autoload_with=session_factory.kw["bind"],
    )


def _add_user(
    session_factory: sessionmaker[Session],
    *,
    user_id: int,
    username: str,
    role: str = "USER",
    password_hash: str = "old-test-hash",
    token_version: int = 4,
) -> None:
    users = _users_table(session_factory)
    with session_factory.begin() as db:
        db.execute(
            insert(users).values(
                id=user_id,
                full_name="Test User",
                username=username,
                password_hash=password_hash,
                role=role,
                is_active=True,
                token_version=token_version,
                created_at=datetime.now(timezone.utc),
            )
        )


def _user_row(
    session_factory: sessionmaker[Session], username: str
) -> dict[str, object]:
    users = _users_table(session_factory)
    with session_factory() as db:
        row = db.execute(
            select(users).where(users.c.username == username)
        ).one()
        return dict(row._mapping)


def test_reset_changes_only_password_and_revokes_existing_tokens(
    password_cli_database: sessionmaker[Session],
) -> None:
    _add_user(
        password_cli_database,
        user_id=1,
        username="testuser01",
        role="USER",
        token_version=4,
    )
    _add_user(
        password_cli_database,
        user_id=2,
        username="other_user",
        role="ADMIN",
        token_version=8,
    )

    with password_cli_database() as db:
        result = reset_existing_user_password(
            db,
            "testuser01",
            "NewPassword123",
        )

    target = _user_row(password_cli_database, "testuser01")
    other = _user_row(password_cli_database, "other_user")
    assert result.status is PasswordResetStatus.RESET
    assert verify_password("NewPassword123", str(target["password_hash"]))
    assert target["token_version"] == 5
    assert target["role"] == "USER"
    assert target["full_name"] == "Test User"
    assert other["password_hash"] == "old-test-hash"
    assert other["token_version"] == 8
    assert other["role"] == "ADMIN"


def test_missing_account_is_reported_without_update(
    password_cli_database: sessionmaker[Session],
) -> None:
    with password_cli_database() as db:
        result = reset_existing_user_password(
            db,
            "missing_user",
            "NewPassword123",
        )

    assert result.status is PasswordResetStatus.NOT_FOUND


def test_password_confirmation_must_match() -> None:
    with pytest.raises(PasswordMismatchError):
        validate_new_password("testuser01", "Password123", "Password456")


@pytest.mark.parametrize(
    "password",
    ["short1", "allletters", "12345678"],
)
def test_registration_password_policy_is_reused(password: str) -> None:
    with pytest.raises(PasswordPolicyError):
        validate_new_password("testuser01", password, password)


def test_database_error_is_safe_and_rolls_back() -> None:
    class BrokenTransaction:
        def __enter__(self) -> None:
            raise SQLAlchemyError("secret persistence detail")

        def __exit__(self, *args: object) -> None:
            return None

    class BrokenSession:
        rollback_called = False

        def begin(self) -> BrokenTransaction:
            return BrokenTransaction()

        def rollback(self) -> None:
            self.rollback_called = True

    session = BrokenSession()
    with pytest.raises(PasswordResetPersistenceError) as raised:
        reset_existing_user_password(
            session,  # type: ignore[arg-type]
            "testuser01",
            "NewPassword123",
        )

    assert session.rollback_called is True
    assert "secret persistence detail" not in str(raised.value)


def test_cli_requires_exact_username_confirmation(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("builtins.input", lambda prompt: "different_user")
    monkeypatch.setattr(
        reset_password.getpass,
        "getpass",
        lambda prompt: pytest.fail("password must not be requested"),
    )
    monkeypatch.setattr(
        reset_password,
        "_run_reset",
        lambda *args: pytest.fail("reset must not run"),
    )

    exit_code = reset_password.main(["testuser01"])

    assert exit_code == 1
    assert "Đã hủy" in capsys.readouterr().out


def test_cli_rejects_mismatched_hidden_passwords_without_database(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    entries = iter(["Password123", "Password456"])
    monkeypatch.setattr("builtins.input", lambda prompt: "testuser01")
    monkeypatch.setattr(
        reset_password.getpass,
        "getpass",
        lambda prompt: next(entries),
    )
    monkeypatch.setattr(
        reset_password,
        "_run_reset",
        lambda *args: pytest.fail("reset must not run"),
    )

    exit_code = reset_password.main(["testuser01"])

    assert exit_code == 2
    captured = capsys.readouterr()
    assert "không khớp" in captured.err
    assert "Password123" not in captured.out + captured.err
    assert "Password456" not in captured.out + captured.err


def test_cli_rejects_invalid_password_without_database(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("builtins.input", lambda prompt: "testuser01")
    monkeypatch.setattr(
        reset_password.getpass,
        "getpass",
        lambda prompt: "allletters",
    )
    monkeypatch.setattr(
        reset_password,
        "_run_reset",
        lambda *args: pytest.fail("reset must not run"),
    )

    exit_code = reset_password.main(["testuser01"])

    assert exit_code == 2
    captured = capsys.readouterr()
    assert "8-128" in captured.err
    assert "allletters" not in captured.out + captured.err


def test_cli_reports_missing_account_without_exposing_password(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    entries = iter(["NewPassword123", "NewPassword123"])
    monkeypatch.setattr("builtins.input", lambda prompt: "testuser01")
    monkeypatch.setattr(
        reset_password.getpass,
        "getpass",
        lambda prompt: next(entries),
    )
    monkeypatch.setattr(
        reset_password,
        "_run_reset",
        lambda username, password: PasswordResetResult(
            PasswordResetStatus.NOT_FOUND,
            username,
        ),
    )

    exit_code = reset_password.main(["testuser01"])

    assert exit_code == 3
    captured = capsys.readouterr()
    assert "Không tìm thấy" in captured.out
    assert "NewPassword123" not in captured.out + captured.err
