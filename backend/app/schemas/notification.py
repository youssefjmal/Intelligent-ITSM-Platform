"""Pydantic schemas for notifications."""

from __future__ import annotations

import datetime as dt
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.core.sanitize import clean_multiline, clean_single_line

ALLOWED_SEVERITIES = {"info", "warning", "critical"}


class NotificationOut(BaseModel):
    id: UUID
    user_id: UUID
    title: str
    body: str | None = None
    severity: str
    link: str | None = None
    source: str | None = None
    created_at: dt.datetime
    read_at: dt.datetime | None = None

    class Config:
        from_attributes = True


class NotificationCreate(BaseModel):
    user_id: UUID | None = None
    title: str = Field(..., min_length=1, max_length=255)
    body: str | None = Field(default=None, max_length=5000)
    severity: str = Field(default="info", max_length=16)
    link: str | None = Field(default=None, max_length=512)
    source: str | None = Field(default=None, max_length=32)

    @field_validator("title", mode="before")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        return clean_single_line(value)

    @field_validator("body", mode="before")
    @classmethod
    def normalize_body(cls, value: str | None) -> str | None:
        cleaned = clean_multiline(value)
        return cleaned or None

    @field_validator("link", "source", mode="before")
    @classmethod
    def normalize_optional(cls, value: str | None) -> str | None:
        cleaned = clean_single_line(value)
        return cleaned or None

    @field_validator("severity", mode="before")
    @classmethod
    def normalize_severity(cls, value: str | None) -> str:
        normalized = clean_single_line(value or "info").lower()
        if normalized not in ALLOWED_SEVERITIES:
            return "info"
        return normalized


class NotificationUnreadCountOut(BaseModel):
    count: int


class SystemNotificationCreate(BaseModel):
    user_id: UUID | None = None
    user_email: str | None = None
    title: str = Field(..., min_length=1, max_length=255)
    body: str | None = Field(default=None, max_length=5000)
    severity: str = Field(default="info", max_length=16)
    link: str | None = Field(default=None, max_length=512)
    source: str = Field(default="n8n", max_length=32)

    @field_validator("title", mode="before")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        return clean_single_line(value)

    @field_validator("body", mode="before")
    @classmethod
    def normalize_body(cls, value: str | None) -> str | None:
        cleaned = clean_multiline(value)
        return cleaned or None

    @field_validator("link", "source", "user_email", mode="before")
    @classmethod
    def normalize_optional(cls, value: str | None) -> str | None:
        cleaned = clean_single_line(value)
        return cleaned or None

    @field_validator("severity", mode="before")
    @classmethod
    def normalize_severity(cls, value: str | None) -> str:
        normalized = clean_single_line(value or "info").lower()
        if normalized not in ALLOWED_SEVERITIES:
            return "info"
        return normalized

