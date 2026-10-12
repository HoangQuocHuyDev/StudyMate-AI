"""Pydantic schemas for user registration."""

from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class UserLogin(BaseModel):
    """Validate credentials without applying registration password rules."""

    model_config = ConfigDict(extra="forbid")

    username: str = Field(
        min_length=3,
        max_length=30,
        pattern=r"^[A-Za-z0-9_]+$",
    )
    password: str = Field(min_length=1, exclude=True)


class TokenResponse(BaseModel):
    """Bearer access token returned after successful authentication."""

    access_token: str
    token_type: str = "bearer"


class UserRegister(BaseModel):
    """Validate data supplied when a user registers an account."""

    model_config = ConfigDict(extra="forbid")

    full_name: str
    username: str = Field(
        min_length=3,
        max_length=30,
        pattern=r"^[A-Za-z0-9_]+$",
    )
    password: str = Field(min_length=8, max_length=128, exclude=True)
    confirm_password: str = Field(exclude=True)

    @field_validator("full_name")
    @classmethod
    def normalize_full_name(cls, value: str) -> str:
        """Trim surrounding whitespace and enforce the normalized length."""

        normalized = value.strip()
        if not 2 <= len(normalized) <= 100:
            raise ValueError("Họ và tên phải có từ 2 đến 100 ký tự.")
        return normalized

    @field_validator("password")
    @classmethod
    def validate_password_content(cls, value: str) -> str:
        """Require at least one letter and one ASCII digit."""

        has_letter = any(character.isalpha() for character in value)
        has_digit = any("0" <= character <= "9" for character in value)
        if not has_letter or not has_digit:
            raise ValueError("Mật khẩu phải chứa ít nhất một chữ cái và một chữ số.")
        return value

    @model_validator(mode="after")
    def validate_password_confirmation(self) -> Self:
        """Require an exact password confirmation match."""

        if self.password != self.confirm_password:
            raise ValueError("Xác nhận mật khẩu không khớp.")
        return self


class UserResponse(BaseModel):
    """Public user data safe to return from an API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    username: str
    role: str
    is_active: bool
    created_at: datetime
