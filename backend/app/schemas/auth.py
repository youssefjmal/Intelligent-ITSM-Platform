"""Auth-related schemas (login response, verification, register)."""

from __future__ import annotations

from pydantic import BaseModel, EmailStr

from app.schemas.user import UserOut


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class VerificationRequest(BaseModel):
    token: str


class VerificationResponse(BaseModel):
    message: str


class RegisterResponse(BaseModel):
    message: str
    verification_token: str | None = None


class ResendVerificationRequest(BaseModel):
    email: EmailStr
