"""Authentication dependencies for protected API routes."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.security import AccessTokenError, decode_access_token
from app.db.session import get_db
from app.models.user import User


_VALID_ROLES = frozenset({"USER", "ADMIN"})


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    """Database user paired with the version asserted by its access token."""

    user: User
    token_version: int


bearer_scheme = HTTPBearer(
    auto_error=False,
    scheme_name="BearerAuth",
    description="Nhập access token JWT nhận được từ endpoint đăng nhập.",
)


def _unauthorized_exception() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Thông tin xác thực không hợp lệ hoặc đã hết hạn.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_authenticated_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Security(bearer_scheme),
    ],
    db: Annotated[Session, Depends(get_db)],
) -> AuthenticatedUser:
    """Validate a token and return its matching active database user."""

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized_exception()

    try:
        claims = decode_access_token(credentials.credentials)
    except AccessTokenError:
        raise _unauthorized_exception() from None

    try:
        user = db.get(User, claims.user_id)
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Không thể xác minh người dùng lúc này.",
        ) from None

    if (
        user is None
        or not user.is_active
        or user.token_version != claims.token_version
    ):
        raise _unauthorized_exception()

    return AuthenticatedUser(
        user=user,
        token_version=claims.token_version,
    )


def get_current_user(
    authenticated: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
) -> User:
    """Return the active user from a version-validated access token."""

    return authenticated.user


def require_roles(*allowed_roles: str) -> Callable[..., User]:
    """Create a dependency that authorizes current database roles."""

    if not allowed_roles:
        raise ValueError("At least one allowed role is required.")

    if any(not isinstance(role, str) for role in allowed_roles):
        raise ValueError("Allowed roles must be USER or ADMIN.")

    invalid_roles = set(allowed_roles) - _VALID_ROLES
    if invalid_roles:
        raise ValueError("Allowed roles must be USER or ADMIN.")

    allowed_role_set = frozenset(allowed_roles)

    def role_dependency(
        current_user: Annotated[User, Depends(get_current_user)],
    ) -> User:
        if current_user.role not in allowed_role_set:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Bạn không có quyền truy cập tài nguyên này.",
            )
        return current_user

    return role_dependency
