"""Administrator-only user-management endpoints."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import require_roles
from app.models.user import User
from app.schemas.admin_users import (
    AdminUserItemResponse,
    AdminUserListResponse,
    AdminUserStatusUpdate,
)
from app.services.admin_users import (
    AdminActorForbiddenError,
    AdminActorInactiveError,
    AdminActorTokenStaleError,
    AdminSelfDeactivationError,
    AdminUserNotFoundError,
    AdminUserQueryError,
    AdminUserUpdateError,
    LastActiveAdminError,
    list_admin_users,
    update_admin_user_status,
)


router = APIRouter(prefix="/admin/users", tags=["Quản trị người dùng"])
AdminUser = Annotated[User, Depends(require_roles("ADMIN"))]
DatabaseSession = Annotated[Session, Depends(get_db)]


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Thông tin xác thực không hợp lệ hoặc đã hết hạn.",
        headers={"WWW-Authenticate": "Bearer"},
    )


@router.get("", response_model=AdminUserListResponse)
def get_users(
    current_admin: AdminUser,
    db: DatabaseSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    search: Annotated[str, Query(max_length=255)] = "",
    role: Annotated[Literal["USER", "ADMIN"] | None, Query()] = None,
    is_active: Annotated[bool | None, Query()] = None,
) -> AdminUserListResponse:
    """List user accounts for an authenticated administrator."""

    del current_admin
    try:
        page = list_admin_users(
            db,
            limit=limit,
            offset=offset,
            search=search,
            role=role,
            is_active=is_active,
        )
    except AdminUserQueryError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Không thể tải danh sách người dùng lúc này.",
        ) from None

    return AdminUserListResponse(
        items=[AdminUserItemResponse.model_validate(user) for user in page.items],
        total=page.total,
        limit=limit,
        offset=offset,
    )


@router.patch(
    "/{user_id}/status",
    response_model=AdminUserItemResponse,
)
def patch_user_status(
    user_id: Annotated[int, Path(gt=0)],
    update: AdminUserStatusUpdate,
    current_admin: AdminUser,
    db: DatabaseSession,
) -> AdminUserItemResponse:
    """Activate or deactivate one account using serialized row locks."""

    actor_token_version = current_admin.token_version
    try:
        updated_user = update_admin_user_status(
            db,
            actor_id=current_admin.id,
            expected_actor_token_version=actor_token_version,
            target_user_id=user_id,
            is_active=update.is_active,
        )
    except (AdminActorInactiveError, AdminActorTokenStaleError):
        raise _unauthorized() from None
    except AdminActorForbiddenError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bạn không có quyền thực hiện thao tác này.",
        ) from None
    except AdminUserNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy người dùng.",
        ) from None
    except AdminSelfDeactivationError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Bạn không thể tự khóa tài khoản đang đăng nhập.",
        ) from None
    except LastActiveAdminError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Không thể khóa quản trị viên đang hoạt động cuối cùng.",
        ) from None
    except AdminUserUpdateError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Không thể cập nhật trạng thái người dùng lúc này.",
        ) from None

    return AdminUserItemResponse.model_validate(updated_user)
