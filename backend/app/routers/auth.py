"""Authentication API routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import (
    AuthenticatedUser,
    get_authenticated_user,
    get_current_user,
)
from app.models.user import User
from app.schemas.user import TokenResponse, UserLogin, UserRegister, UserResponse
from app.services.auth_service import (
    InvalidCredentialsError,
    StaleAccessTokenError,
    TokenRevocationError,
    UsernameAlreadyExistsError,
    UserAuthenticationError,
    UserRegistrationError,
    authenticate_user,
    register_user,
    revoke_access_token,
)
from app.services.auth_rate_limiter import (
    AuthenticationRateLimiter,
    AuthenticationRateLimitExceeded,
    get_authentication_rate_limiter,
)


router = APIRouter(prefix="/auth", tags=["Xác thực"])


def _client_host(request: Request) -> str:
    """Use only the ASGI peer; untrusted forwarding headers are ignored."""

    return request.client.host if request.client is not None else "unknown-client"


def _raise_rate_limited(error: AuthenticationRateLimitExceeded) -> None:
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Quá nhiều yêu cầu xác thực. Vui lòng thử lại sau.",
        headers={"Retry-After": str(error.retry_after)},
    ) from None


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
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
)
def logout_account(
    authenticated: Annotated[
        AuthenticatedUser,
        Depends(get_authenticated_user),
    ],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    """Atomically revoke the current user's issued token generation."""

    try:
        revoke_access_token(
            db,
            user_id=authenticated.user.id,
            expected_token_version=authenticated.token_version,
        )
    except StaleAccessTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Thông tin xác thực không hợp lệ hoặc đã hết hạn.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
    except TokenRevocationError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Không thể đăng xuất lúc này.",
        ) from None

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
)
def login_account(
    request: Request,
    credentials: UserLogin,
    db: Annotated[Session, Depends(get_db)],
    rate_limiter: Annotated[
        AuthenticationRateLimiter,
        Depends(get_authentication_rate_limiter),
    ],
) -> TokenResponse:
    """Authenticate an active account and issue an access token."""

    try:
        rate_limiter.check_login(
            client_host=_client_host(request),
            username=credentials.username,
        )
    except AuthenticationRateLimitExceeded as error:
        _raise_rate_limited(error)

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
    request: Request,
    registration: UserRegister,
    db: Annotated[Session, Depends(get_db)],
    rate_limiter: Annotated[
        AuthenticationRateLimiter,
        Depends(get_authentication_rate_limiter),
    ],
) -> UserResponse:
    """Register a standard user account."""

    try:
        rate_limiter.check_register(client_host=_client_host(request))
    except AuthenticationRateLimitExceeded as error:
        _raise_rate_limited(error)

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
