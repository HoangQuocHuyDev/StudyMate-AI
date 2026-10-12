"""Authentication API routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.user import TokenResponse, UserLogin, UserRegister, UserResponse
from app.services.auth_service import (
    InvalidCredentialsError,
    UsernameAlreadyExistsError,
    UserAuthenticationError,
    UserRegistrationError,
    authenticate_user,
    register_user,
)


router = APIRouter(prefix="/auth", tags=["Xác thực"])


@router.get(
    "/me",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
)
def read_current_user(
    current_user: Annotated[User, Depends(get_current_user)],
) -> UserResponse:
    """Return the authenticated user's current database profile."""

    return UserResponse.model_validate(current_user)


@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
)
def login_account(
    credentials: UserLogin,
    db: Annotated[Session, Depends(get_db)],
) -> TokenResponse:
    """Authenticate an active account and issue an access token."""

    try:
        access_token = authenticate_user(db, credentials)
    except InvalidCredentialsError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tên đăng nhập hoặc mật khẩu không chính xác.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
    except UserAuthenticationError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Không thể đăng nhập lúc này.",
        ) from None

    return TokenResponse(access_token=access_token)


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
def register_account(
    registration: UserRegister,
    db: Annotated[Session, Depends(get_db)],
) -> UserResponse:
    """Register a standard user account."""

    try:
        return register_user(db, registration)
    except UsernameAlreadyExistsError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Tên đăng nhập đã tồn tại.",
        ) from None
    except UserRegistrationError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Không thể tạo tài khoản lúc này.",
        ) from None
