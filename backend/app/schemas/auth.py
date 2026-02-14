"""Auth-related schemas (login response, verification, register)."""

from __future__ import annotations

import re
import unicodedata

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.schemas.user import UserOut
from app.core.sanitize import clean_email, clean_single_line


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserOut


class TokenRefreshRequest(BaseModel):
    refresh_token: str

    @field_validator("refresh_token", mode="before")
    @classmethod
    def normalize_refresh_token(cls, value: str) -> str:
        return clean_single_line(value)


class VerificationRequest(BaseModel):
    token: str = Field(min_length=16, max_length=64)

    @field_validator("token", mode="before")
    @classmethod
    def normalize_token(cls, value: str) -> str:
        return clean_single_line(value)


class VerificationCodeRequest(BaseModel):
    email: EmailStr
    code: str = Field(min_length=6, max_length=6)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return clean_email(value)

    @field_validator("code", mode="before")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        code = clean_single_line(value).replace(" ", "")
        if not re.fullmatch(r"\d{6}", code):
            raise ValueError("invalid_verification_code")
        return code


class VerificationResponse(BaseModel):
    message: str
    auto_logged_in: bool = False
    user: UserOut | None = None


class RegisterResponse(BaseModel):
    message: str
    verification_token: str | None = None
    verification_code: str | None = None


class EmailLoginResponse(BaseModel):
    message: str
    user: UserOut | None = None
    requires_verification: bool = False
    verification_token: str | None = None
    verification_code: str | None = None


class ResendVerificationRequest(BaseModel):
    email: EmailStr

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return clean_email(value)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return clean_email(value)


class ForgotPasswordResponse(BaseModel):
    message: str


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=16, max_length=64)
    new_password: str = Field(min_length=8, max_length=128)

    @field_validator("token", mode="before")
    @classmethod
    def normalize_token(cls, value: str) -> str:
        return clean_single_line(value)

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, value: str) -> str:
        if any(unicodedata.category(ch) == "Cc" for ch in value):
            raise ValueError("password_contains_control_chars")
        if not value.strip():
            raise ValueError("password_required")
        return value


class ResetPasswordResponse(BaseModel):
    message: str
