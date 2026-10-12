"""Authentication dependencies for protected API routes."""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.security import AccessTokenError, decode_access_token
from app.db.session import get_db
from app.models.user import User


_VALID_ROLES = frozenset({"USER", "ADMIN"})


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


def get_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Security(bearer_scheme),
    ],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    """Return the active database user represented by a valid access token."""

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized_exception()

    try:
        user_id = decode_access_token(credentials.credentials)
    except AccessTokenError:
        raise _unauthorized_exception() from None

    try:
        user = db.get(User, user_id)
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Không thể xác minh người dùng lúc này.",
        ) from None

    if user is None or not user.is_active:
        raise _unauthorized_exception()

    return user


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
