"""Pydantic schemas for tickets, comments, and analytics."""

from __future__ import annotations

import datetime as dt
from pydantic import BaseModel, Field, field_validator

from app.models.enums import TicketCategory, TicketPriority, TicketStatus
from app.core.sanitize import clean_list, clean_multiline, clean_single_line

MAX_TITLE_LEN = 120
MAX_DESCRIPTION_LEN = 4000
MAX_NAME_LEN = 80
MAX_TAGS = 10
MAX_TAG_LEN = 32


class TicketCommentOut(BaseModel):
    id: str
    author: str
    content: str
    created_at: dt.datetime

    class Config:
        from_attributes = True


class TicketBase(BaseModel):
    title: str = Field(min_length=3, max_length=MAX_TITLE_LEN)
    description: str = Field(min_length=5, max_length=MAX_DESCRIPTION_LEN)
    priority: TicketPriority
    category: TicketCategory
    assignee: str | None = Field(default=None, min_length=2, max_length=MAX_NAME_LEN)
    reporter: str = Field(min_length=2, max_length=MAX_NAME_LEN)
    tags: list[str] = Field(default_factory=list, max_length=MAX_TAGS)

    @field_validator("title", mode="before")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        return clean_single_line(value)

    @field_validator("description", mode="before")
    @classmethod
    def normalize_description(cls, value: str) -> str:
        return clean_multiline(value)

    @field_validator("reporter", mode="before")
    @classmethod
    def normalize_reporter(cls, value: str) -> str:
        return clean_single_line(value)

    @field_validator("assignee", mode="before")
    @classmethod
    def normalize_assignee(cls, value: str | None) -> str | None:
        cleaned = clean_single_line(value)
        return cleaned or None

    @field_validator("tags", mode="before")
    @classmethod
    def normalize_tags(cls, value: list[str]) -> list[str]:
        return clean_list(value, max_items=MAX_TAGS, item_max_length=MAX_TAG_LEN)


class TicketCreate(TicketBase):
    auto_priority_applied: bool = False
    assignment_model_version: str | None = Field(default=None, max_length=40)
    priority_model_version: str | None = Field(default=None, max_length=40)
    predicted_priority: TicketPriority | None = None
    predicted_category: TicketCategory | None = None

    @field_validator("assignment_model_version", "priority_model_version", mode="before")
    @classmethod
    def normalize_model_versions(cls, value: str | None) -> str | None:
        cleaned = clean_single_line(value)
        return cleaned or None


class TicketStatusUpdate(BaseModel):
    status: TicketStatus
    comment: str | None = Field(default=None, max_length=MAX_DESCRIPTION_LEN)

    @field_validator("comment", mode="before")
    @classmethod
    def normalize_comment(cls, value: str | None) -> str | None:
        cleaned = clean_multiline(value)
        return cleaned or None


class TicketTriageUpdate(BaseModel):
    assignee: str | None = Field(default=None, min_length=2, max_length=MAX_NAME_LEN)
    priority: TicketPriority | None = None
    category: TicketCategory | None = None
    comment: str | None = Field(default=None, max_length=MAX_DESCRIPTION_LEN)

    @field_validator("assignee", mode="before")
    @classmethod
    def normalize_assignee(cls, value: str | None) -> str | None:
        cleaned = clean_single_line(value)
        return cleaned or None

    @field_validator("comment", mode="before")
    @classmethod
    def normalize_comment(cls, value: str | None) -> str | None:
        cleaned = clean_multiline(value)
        return cleaned or None


class TicketOut(TicketBase):
    id: str
    status: TicketStatus
    auto_assignment_applied: bool
    auto_priority_applied: bool
    assignment_model_version: str
    priority_model_version: str
    predicted_priority: TicketPriority | None
    predicted_category: TicketCategory | None
    assignment_change_count: int
    first_action_at: dt.datetime | None
    resolved_at: dt.datetime | None
    created_at: dt.datetime
    updated_at: dt.datetime
    resolution: str | None
    comments: list[TicketCommentOut]

    class Config:
        from_attributes = True


class TicketStats(BaseModel):
    total: int
    open: int
    in_progress: int
    pending: int
    resolved: int
    closed: int
    critical: int
    high: int
    resolution_rate: int
    avg_resolution_days: float


class WeeklyBucket(BaseModel):
    week: str
    opened: int
    closed: int
    pending: int


class BeforeAfterMetric(BaseModel):
    before: float | None
    after: float | None


class TicketPerformanceOut(BaseModel):
    total_tickets: int
    resolved_tickets: int
    mttr_hours: BeforeAfterMetric
    reassignment_rate: float
    reassigned_tickets: int
    avg_time_to_first_action_hours: float | None
    classification_accuracy_rate: float | None
    classification_samples: int
    auto_assignment_accuracy_rate: float | None
    auto_assignment_samples: int
