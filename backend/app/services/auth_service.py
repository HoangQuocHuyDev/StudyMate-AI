"""Authentication-related application services."""

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.security import (
    JWTConfigurationError,
    create_access_token,
    hash_password,
    verify_password,
)
from app.models.user import User
from app.schemas.user import (
    UserLogin,
    UserPasswordChange,
    UserProfileUpdate,
    UserRegister,
)


_DUMMY_PASSWORD_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$8BOpB6ohwkV6OOA9aEXOsQ$"
    "E+lGIdSoaC4t+QxloQ+iXDFKBHPM8YEp8ovBWuGjEaw"
)


class UsernameAlreadyExistsError(Exception):
    """Raised when a registration username is already in use."""


class UserRegistrationError(Exception):
    """Raised when a user cannot be persisted safely."""


class InvalidCredentialsError(Exception):
    """Raised when credentials cannot authenticate an active account."""


class UserAuthenticationError(Exception):
    """Raised when authentication cannot be completed safely."""


class StaleAccessTokenError(Exception):
    """Raised when another request has already revoked this token version."""


class TokenRevocationError(Exception):
    """Raised when token revocation cannot be persisted safely."""


class UserProfileUpdateError(Exception):
    """Raised when an authenticated profile update cannot be persisted."""


class InvalidCurrentPasswordError(Exception):
    """Raised when a password change does not prove the current password."""


class StaleAccountUpdateError(Exception):
    """Raised when the authenticated account changed during an update."""


class PasswordChangeError(Exception):
    """Raised when a password change cannot be persisted safely."""


def _is_username_unique_violation(error: IntegrityError) -> bool:
    """Return whether PostgreSQL reported the username unique constraint."""

    original_error = error.orig
    sqlstate = getattr(original_error, "sqlstate", None) or getattr(
        original_error,
        "pgcode",
        None,
    )
    diagnostic = getattr(original_error, "diag", None)
    constraint_name = getattr(diagnostic, "constraint_name", None)

    return sqlstate == "23505" and constraint_name == "uq_users_username"


def register_user(db: Session, registration: UserRegister) -> User:
    """Create a standard active user account from validated registration data."""

    try:
        existing_user_id = db.scalar(
            select(User.id).where(User.username == registration.username)
        )
    except SQLAlchemyError as error:
        db.rollback()
        raise UserRegistrationError from error

    if existing_user_id is not None:
        raise UsernameAlreadyExistsError

    user = User(
        full_name=registration.full_name,
        username=registration.username,
        password_hash=hash_password(registration.password),
        role="USER",
        is_active=True,
    )

    try:
        db.add(user)
        db.flush()
        db.refresh(user)
        db.commit()
    except IntegrityError as error:
        db.rollback()
        if _is_username_unique_violation(error):
            raise UsernameAlreadyExistsError from None
        raise UserRegistrationError from error
    except SQLAlchemyError as error:
        db.rollback()
        raise UserRegistrationError from error

    return user


def authenticate_user(db: Session, credentials: UserLogin) -> str:
    """Authenticate an active user and return a signed access token."""

    try:
        user = db.scalar(
            select(User).where(User.username == credentials.username)
        )
    except SQLAlchemyError as error:
        db.rollback()
        raise UserAuthenticationError from error

    if user is None:
        verify_password(credentials.password, _DUMMY_PASSWORD_HASH)
        raise InvalidCredentialsError

    password_is_valid = verify_password(
        credentials.password,
        user.password_hash,
    )
    if not password_is_valid or not user.is_active:
        raise InvalidCredentialsError

    try:
        return create_access_token(user.id, user.token_version)
    except (JWTConfigurationError, ValueError) as error:
        raise UserAuthenticationError from error


def revoke_access_token(
    db: Session,
    *,
    user_id: int,
    expected_token_version: int,
) -> None:
    """Atomically revoke every token issued at the expected user version."""

    statement = (
        update(User)
        .where(
            User.id == user_id,
            User.token_version == expected_token_version,
        )
        .values(token_version=User.token_version + 1)
    )
    try:
        result = db.execute(statement)
        if result.rowcount != 1:
            db.rollback()
            raise StaleAccessTokenError
        db.commit()
    except StaleAccessTokenError:
        raise
    except SQLAlchemyError as error:
        db.rollback()
        raise TokenRevocationError from error


def update_current_user_profile(
    db: Session,
    *,
    user: User,
    expected_token_version: int,
    update_data: UserProfileUpdate,
) -> User:
    """Update only the authenticated account's display name."""

    statement = (
        update(User)
        .where(
            User.id == user.id,
            User.is_active.is_(True),
            User.token_version == expected_token_version,
        )
        .values(full_name=update_data.full_name)
        .execution_options(synchronize_session=False)
    )
    try:
        result = db.execute(statement)
        if result.rowcount != 1:
            db.rollback()
            raise StaleAccountUpdateError
        db.commit()
        user.full_name = update_data.full_name
        return user
    except StaleAccountUpdateError:
        raise
    except SQLAlchemyError:
        db.rollback()
        raise UserProfileUpdateError from None


def change_current_user_password(
    db: Session,
    *,
    user: User,
    expected_token_version: int,
    password_change: UserPasswordChange,
) -> None:
    """Replace one password and revoke all previously issued access tokens."""

    if not verify_password(password_change.current_password, user.password_hash):
        raise InvalidCurrentPasswordError

    new_password_hash = hash_password(password_change.new_password)
    statement = (
        update(User)
        .where(
            User.id == user.id,
            User.is_active.is_(True),
            User.token_version == expected_token_version,
        )
        .values(
            password_hash=new_password_hash,
            token_version=User.token_version + 1,
        )
        .execution_options(synchronize_session=False)
    )
    try:
        result = db.execute(statement)
        if result.rowcount != 1:
            db.rollback()
            raise StaleAccountUpdateError
        db.commit()
    except StaleAccountUpdateError:
        raise
    except SQLAlchemyError:
        db.rollback()
        raise PasswordChangeError from None
