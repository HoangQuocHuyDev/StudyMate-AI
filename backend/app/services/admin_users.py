"""Administrator user-listing and account-status application services."""

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.user import User


class AdminUserQueryError(Exception):
    """Raised when the administrator user list cannot be loaded safely."""


class AdminUserUpdateError(Exception):
    """Raised when an account status change cannot be persisted safely."""


class AdminUserNotFoundError(Exception):
    """Raised when the target account does not exist."""


class AdminActorInactiveError(Exception):
    """Raised when the acting administrator is no longer active."""


class AdminActorForbiddenError(Exception):
    """Raised when the actor no longer has the administrator role."""


class AdminActorTokenStaleError(Exception):
    """Raised when the actor's token version changed before row locking."""


class AdminSelfDeactivationError(Exception):
    """Raised when an administrator attempts to deactivate itself."""


class LastActiveAdminError(Exception):
    """Raised when a change would deactivate the final active administrator."""


@dataclass(frozen=True, slots=True)
class AdminUserListPage:
    items: list[User]
    total: int


def _admin_lock_statement():
    """Build the shared, deterministic lock statement for admin rows."""

    return (
        select(
            User.id,
            User.is_active,
            User.token_version,
        )
        .where(User.role == "ADMIN")
        .order_by(User.id.asc())
        .with_for_update()
    )


def _escape_like_literal(value: str) -> str:
    """Escape PostgreSQL LIKE metacharacters and the escape character itself."""

    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def list_admin_users(
    db: Session,
    *,
    limit: int,
    offset: int,
    search: str = "",
    role: str | None = None,
    is_active: bool | None = None,
) -> AdminUserListPage:
    """Return one stable page of users without exposing authentication fields."""

    normalized_search = search.strip()
    filters = []
    if normalized_search:
        escaped_search = _escape_like_literal(normalized_search)
        filters.append(User.username.ilike(f"%{escaped_search}%", escape="\\"))
    if role is not None:
        filters.append(User.role == role)
    if is_active is not None:
        filters.append(User.is_active.is_(is_active))

    count_statement = select(func.count(User.id)).where(*filters)
    page_statement = (
        select(User)
        .where(*filters)
        .order_by(User.created_at.desc(), User.id.desc())
        .offset(offset)
        .limit(limit)
    )

    try:
        total = int(db.scalar(count_statement) or 0)
        items = list(db.scalars(page_statement).all())
    except SQLAlchemyError:
        db.rollback()
        raise AdminUserQueryError from None

    return AdminUserListPage(items=items, total=total)


def update_admin_user_status(
    db: Session,
    *,
    actor_id: int,
    expected_actor_token_version: int,
    target_user_id: int,
    is_active: bool,
) -> User:
    """Change one account status while serializing all administrator changes.

    Every call first locks all administrator rows in ascending primary-key order,
    then locks the target row. This common ordering prevents two status requests
    from independently deciding that they may deactivate the last active admin.
    """

    try:
        admin_rows = db.execute(_admin_lock_statement()).all()

        actor_row = next((row for row in admin_rows if row.id == actor_id), None)
        if actor_row is None:
            db.rollback()
            raise AdminActorForbiddenError
        if not actor_row.is_active:
            db.rollback()
            raise AdminActorInactiveError
        if actor_row.token_version != expected_actor_token_version:
            db.rollback()
            raise AdminActorTokenStaleError

        target = db.scalar(
            select(User)
            .where(User.id == target_user_id)
            .execution_options(populate_existing=True)
            .with_for_update()
        )
        if target is None:
            db.rollback()
            raise AdminUserNotFoundError

        if target.id == actor_id and not is_active:
            db.rollback()
            raise AdminSelfDeactivationError

        if bool(target.is_active) == is_active:
            db.commit()
            return target

        if target.role == "ADMIN" and not is_active:
            active_admin_count = sum(row.is_active for row in admin_rows)
            if active_admin_count <= 1:
                db.rollback()
                raise LastActiveAdminError

        target.is_active = is_active
        target.token_version += 1
        db.commit()
        return target
    except (
        AdminActorForbiddenError,
        AdminActorInactiveError,
        AdminActorTokenStaleError,
        AdminSelfDeactivationError,
        AdminUserNotFoundError,
        LastActiveAdminError,
    ):
        raise
    except SQLAlchemyError:
        db.rollback()
        raise AdminUserUpdateError from None
