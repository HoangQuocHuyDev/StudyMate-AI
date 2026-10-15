"""Tests for the manually invoked ADMIN promotion CLI."""

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

from scripts import promote_admin
from scripts.promote_admin import (
    PromotionPersistenceError,
    PromotionResult,
    PromotionStatus,
    promote_existing_user,
)


@pytest.fixture
def admin_cli_database() -> sessionmaker[Session]:
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


def _add_user(
    session_factory: sessionmaker[Session],
    *,
    user_id: int,
    username: str,
    role: str,
    password_hash: str = "test-only-hash",
) -> None:
    with session_factory.begin() as db:
        db.execute(
            insert(Table("users", MetaData(), autoload_with=db.get_bind())).values(
                id=user_id,
                full_name="Test User",
                username=username,
                password_hash=password_hash,
                role=role,
                is_active=True,
                token_version=7,
                created_at=datetime.now(timezone.utc),
            )
        )


def _user_row(
    session_factory: sessionmaker[Session], username: str
) -> dict[str, object]:
    users = Table("users", MetaData(), autoload_with=session_factory.kw["bind"])
    with session_factory() as db:
        return dict(db.execute(select(users).where(users.c.username == username)).one()._mapping)


def test_promotes_exactly_one_user_and_preserves_other_fields(
    admin_cli_database: sessionmaker[Session],
) -> None:
    _add_user(
        admin_cli_database,
        user_id=1,
        username="target_user",
        role="USER",
        password_hash="unchanged-sensitive-hash",
    )
    _add_user(
        admin_cli_database,
        user_id=2,
        username="other_user",
        role="USER",
    )

    with admin_cli_database() as db:
        result = promote_existing_user(db, "target_user")

    target = _user_row(admin_cli_database, "target_user")
    other = _user_row(admin_cli_database, "other_user")
    assert result.status is PromotionStatus.PROMOTED
    assert target["role"] == "ADMIN"
    assert target["password_hash"] == "unchanged-sensitive-hash"
    assert target["token_version"] == 7
    assert other["role"] == "USER"


def test_already_admin_is_reported_without_update(
    admin_cli_database: sessionmaker[Session],
) -> None:
    _add_user(
        admin_cli_database,
        user_id=1,
        username="existing_admin",
        role="ADMIN",
    )

    with admin_cli_database() as db:
        result = promote_existing_user(db, "existing_admin")

    assert result.status is PromotionStatus.ALREADY_ADMIN
    assert _user_row(admin_cli_database, "existing_admin")["role"] == "ADMIN"


def test_missing_username_is_reported_without_update(
    admin_cli_database: sessionmaker[Session],
) -> None:
    with admin_cli_database() as db:
        result = promote_existing_user(db, "missing_user")

    assert result.status is PromotionStatus.NOT_FOUND


def test_invalid_username_is_rejected_before_database_access() -> None:
    class SessionThatMustNotBeUsed:
        def begin(self) -> None:
            raise AssertionError("database must not be accessed")

    with pytest.raises(ValueError):
        promote_existing_user(SessionThatMustNotBeUsed(), "invalid user")  # type: ignore[arg-type]


def test_database_error_is_wrapped_and_rolled_back() -> None:
    class BrokenTransaction:
        def __enter__(self) -> None:
            raise SQLAlchemyError("sensitive database detail")

        def __exit__(self, *args: object) -> None:
            return None

    class BrokenSession:
        rollback_called = False

        def begin(self) -> BrokenTransaction:
            return BrokenTransaction()

        def rollback(self) -> None:
            self.rollback_called = True

    session = BrokenSession()
    with pytest.raises(PromotionPersistenceError) as raised:
        promote_existing_user(session, "target_user")  # type: ignore[arg-type]

    assert session.rollback_called is True
    assert "sensitive database detail" not in str(raised.value)


def test_cli_cancellation_never_runs_promotion(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("builtins.input", lambda prompt: "different_user")
    monkeypatch.setattr(
        promote_admin,
        "_run_promotion",
        lambda username: pytest.fail("promotion must not run"),
    )

    exit_code = promote_admin.main(["target_user"])

    assert exit_code == 1
    assert "Đã hủy" in capsys.readouterr().out


def test_cli_confirmed_promotion_reports_success(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("builtins.input", lambda prompt: "target_user")
    monkeypatch.setattr(
        promote_admin,
        "_run_promotion",
        lambda username: PromotionResult(PromotionStatus.PROMOTED, username),
    )

    exit_code = promote_admin.main(["target_user"])

    assert exit_code == 0
    output = capsys.readouterr()
    assert "thành công" in output.out
    assert output.err == ""


def test_cli_help_is_printable_with_vietnamese_text(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as raised:
        promote_admin.main(["--help"])

    assert raised.value.code == 0
    assert "studymate_ai_db" in capsys.readouterr().out
