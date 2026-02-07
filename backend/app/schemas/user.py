"""Pydantic schemas for user payloads and responses."""

from __future__ import annotations

import datetime as dt
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.models.enums import UserRole


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)
    name: str
    role: UserRole = UserRole.viewer


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: UUID
    email: EmailStr
    name: str
    role: UserRole
    is_verified: bool
    created_at: dt.datetime

    class Config:
        from_attributes = True


class UserRoleUpdate(BaseModel):
    role: UserRole


class UserAssigneeOut(BaseModel):
    id: UUID
    name: str
    role: UserRole

    class Config:
        from_attributes = True
