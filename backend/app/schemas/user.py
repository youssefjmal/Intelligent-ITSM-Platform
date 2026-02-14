"""Pydantic schemas for user payloads and responses."""

from __future__ import annotations

import datetime as dt
import unicodedata
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models.enums import SeniorityLevel, UserRole
from app.core.sanitize import clean_email, clean_list, clean_single_line

MAX_NAME_LEN = 80
MAX_SPECIALIZATIONS = 12
MAX_SPECIALIZATION_LEN = 32


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(min_length=2, max_length=MAX_NAME_LEN)
    specializations: list[str] = Field(default_factory=list, max_length=MAX_SPECIALIZATIONS)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return clean_email(value)

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return clean_single_line(value)

    @field_validator("specializations", mode="before")
    @classmethod
    def normalize_specializations(cls, value: list[str]) -> list[str]:
        return clean_list(
            value,
            max_items=MAX_SPECIALIZATIONS,
            item_max_length=MAX_SPECIALIZATION_LEN,
        )

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        if any(unicodedata.category(ch) == "Cc" for ch in value):
            raise ValueError("password_contains_control_chars")
        if not value.strip():
            raise ValueError("password_required")
        return value


class UserLogin(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return clean_email(value)

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        if any(unicodedata.category(ch) == "Cc" for ch in value):
            raise ValueError("password_contains_control_chars")
        if not value.strip():
            raise ValueError("password_required")
        return value


class UserOut(BaseModel):
    id: UUID
    email: EmailStr
    name: str
    role: UserRole
    is_verified: bool
    created_at: dt.datetime
    specializations: list[str]
    seniority_level: SeniorityLevel
    is_available: bool
    max_concurrent_tickets: int

    class Config:
        from_attributes = True


class UserRoleUpdate(BaseModel):
    role: UserRole


class UserSeniorityUpdate(BaseModel):
    seniority_level: SeniorityLevel


class UserSpecializationsUpdate(BaseModel):
    specializations: list[str] = Field(default_factory=list, max_length=MAX_SPECIALIZATIONS)

    @field_validator("specializations", mode="before")
    @classmethod
    def normalize_specializations(cls, value: list[str]) -> list[str]:
        return clean_list(
            value,
            max_items=MAX_SPECIALIZATIONS,
            item_max_length=MAX_SPECIALIZATION_LEN,
        )


class UserAssigneeOut(BaseModel):
    id: UUID
    name: str
    role: UserRole
    specializations: list[str]
    seniority_level: SeniorityLevel
    is_available: bool
    max_concurrent_tickets: int

    class Config:
        from_attributes = True
