"""Pydantic schemas for notifications."""

from __future__ import annotations

import datetime as dt
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.core.sanitize import clean_multiline, clean_single_line

ALLOWED_SEVERITIES = {"info", "warning", "high", "critical"}


class NotificationOut(BaseModel):
    id: UUID
    user_id: UUID
    title: str
    body: str | None = None
    severity: str
    link: str | None = None
    source: str | None = None
    metadata_json: dict | None = None
    action_type: str | None = None
    action_payload: dict | None = None
    created_at: dt.datetime
    read_at: dt.datetime | None = None

    class Config:
        from_attributes = True


class NotificationCreate(BaseModel):
    user_id: UUID | None = None
    ticket_id: str | None = Field(default=None, min_length=3, max_length=32)
    problem_id: str | None = Field(default=None, min_length=3, max_length=32)
    type: str | None = Field(default=None, max_length=24)
    title: str = Field(..., min_length=1, max_length=255)
    body: str | None = Field(default=None, max_length=5000)
    severity: str = Field(default="info", max_length=16)
    link: str | None = Field(default=None, max_length=512)
    source: str | None = Field(default=None, max_length=32)
    metadata_json: dict | None = None
    action_type: str | None = Field(default=None, max_length=24)
    action_payload: dict | None = None

    @field_validator("title", mode="before")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        return clean_single_line(value)

    @field_validator("body", mode="before")
    @classmethod
    def normalize_body(cls, value: str | None) -> str | None:
        cleaned = clean_multiline(value)
        return cleaned or None

    @field_validator("link", "source", "type", "action_type", mode="before")
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
    user_name: str | None = None
    ticket_id: str | None = Field(default=None, min_length=3, max_length=32)
    problem_id: str | None = Field(default=None, min_length=3, max_length=32)
    type: str | None = Field(default=None, max_length=24)
    title: str = Field(..., min_length=1, max_length=255)
    body: str | None = Field(default=None, max_length=5000)
    severity: str = Field(default="info", max_length=16)
    link: str | None = Field(default=None, max_length=512)
    source: str = Field(default="n8n", max_length=32)
    metadata_json: dict | None = None
    action_type: str | None = Field(default=None, max_length=24)
    action_payload: dict | None = None

    @field_validator("title", mode="before")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        return clean_single_line(value)

    @field_validator("body", mode="before")
    @classmethod
    def normalize_body(cls, value: str | None) -> str | None:
        cleaned = clean_multiline(value)
        return cleaned or None

    @field_validator("link", "source", "user_email", "user_name", "type", "action_type", mode="before")
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


class NotificationPreferencesOut(BaseModel):
    email_enabled: bool
    email_min_severity: str
    digest_frequency: str
    quiet_hours_start: str | None = None
    quiet_hours_end: str | None = None


class NotificationPreferencesPatch(BaseModel):
    email_enabled: bool | None = None
    email_min_severity: str | None = Field(default=None, max_length=16)
    digest_frequency: str | None = Field(default=None, max_length=24)
    quiet_hours_start: str | None = Field(default=None, max_length=8)
    quiet_hours_end: str | None = Field(default=None, max_length=8)

    @field_validator("email_min_severity", mode="before")
    @classmethod
    def normalize_min_severity(cls, value: str | None) -> str | None:
        cleaned = clean_single_line(value).lower() if value is not None else None
        if cleaned and cleaned not in ALLOWED_SEVERITIES:
            return "critical"
        return cleaned

    @field_validator("digest_frequency", mode="before")
    @classmethod
    def normalize_digest_frequency(cls, value: str | None) -> str | None:
        cleaned = clean_single_line(value).lower() if value is not None else None
        if cleaned and cleaned not in {"none", "hourly"}:
            return "hourly"
        return cleaned


class NotificationDebugOut(BaseModel):
    notification_id: UUID
    user_id: UUID
    title: str
    severity: str
    source: str | None = None
    workflow_name: str | None = None
    trace_id: str | None = None
    recipients: list[str] = Field(default_factory=list)
    duplicate_suppression: str | None = None
    delivery_status: str
    created_at: dt.datetime


class NotificationAnalyticsOut(BaseModel):
    notifications_created_total: dict[str, int] = Field(default_factory=dict)
    notifications_read_rate: dict[str, float] = Field(default_factory=dict)
    email_delivery_rate: dict[str, int] = Field(default_factory=dict)
