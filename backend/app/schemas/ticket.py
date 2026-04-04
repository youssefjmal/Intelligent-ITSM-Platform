"""Pydantic schemas for tickets, comments, and analytics."""

from __future__ import annotations

import datetime as dt
from typing import Any
from pydantic import BaseModel, Field, field_validator

from app.models.enums import TicketCategory, TicketPriority, TicketStatus, TicketType
from app.core.ticket_limits import MAX_TAG_LEN, MAX_TAGS
from app.core.sanitize import clean_list, clean_multiline, clean_single_line

MAX_TITLE_LEN = 120
MAX_DESCRIPTION_LEN = 4000
MAX_NAME_LEN = 80


def _normalize_datetime_value(value: Any) -> dt.datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, dt.datetime):
        parsed = value
    elif isinstance(value, dt.date):
        parsed = dt.datetime.combine(value, dt.time.min)
    elif isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        candidate = raw.replace("Z", "+00:00")
        if len(candidate) == 10 and candidate.count("-") == 2:
            candidate = f"{candidate}T12:00:00+00:00"
        parsed = dt.datetime.fromisoformat(candidate)
    else:
        raise ValueError("invalid_datetime")

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


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
    ticket_type: TicketType = TicketType.service_request
    category: TicketCategory
    due_at: dt.datetime | None = None
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

    @field_validator("due_at", mode="before")
    @classmethod
    def normalize_due_at(cls, value: Any) -> dt.datetime | None:
        return _normalize_datetime_value(value)


class TicketCreate(TicketBase):
    auto_priority_applied: bool = False
    assignment_model_version: str | None = Field(default=None, max_length=40)
    priority_model_version: str | None = Field(default=None, max_length=40)
    predicted_priority: TicketPriority | None = None
    predicted_ticket_type: TicketType | None = None
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
    title: str | None = Field(default=None, min_length=3, max_length=MAX_TITLE_LEN)
    description: str | None = Field(default=None, min_length=5, max_length=MAX_DESCRIPTION_LEN)
    assignee: str | None = Field(default=None, min_length=2, max_length=MAX_NAME_LEN)
    priority: TicketPriority | None = None
    ticket_type: TicketType | None = None
    category: TicketCategory | None = None
    due_at: dt.datetime | None = None
    comment: str | None = Field(default=None, max_length=MAX_DESCRIPTION_LEN)

    @field_validator("title", mode="before")
    @classmethod
    def normalize_title(cls, value: str | None) -> str | None:
        cleaned = clean_single_line(value)
        return cleaned or None

    @field_validator("description", mode="before")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        cleaned = clean_multiline(value)
        return cleaned or None

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

    @field_validator("due_at", mode="before")
    @classmethod
    def normalize_due_at(cls, value: Any) -> dt.datetime | None:
        return _normalize_datetime_value(value)


class TicketOut(TicketBase):
    id: str
    problem_id: str | None = None
    status: TicketStatus
    auto_assignment_applied: bool
    auto_priority_applied: bool
    assignment_model_version: str
    priority_model_version: str
    predicted_priority: TicketPriority | None
    predicted_ticket_type: TicketType | None
    predicted_category: TicketCategory | None
    assignment_change_count: int
    first_action_at: dt.datetime | None
    resolved_at: dt.datetime | None
    due_at: dt.datetime | None = None
    sla_status: str | None = None
    sla_remaining_minutes: int | None = None
    sla_first_response_due_at: dt.datetime | None = None
    sla_resolution_due_at: dt.datetime | None = None
    sla_first_response_breached: bool = False
    sla_resolution_breached: bool = False
    sla_last_synced_at: dt.datetime | None = None
    created_at: dt.datetime
    updated_at: dt.datetime
    resolution: str | None
    comments: list[TicketCommentOut]

    class Config:
        from_attributes = True


class TicketHistoryChange(BaseModel):
    field: str
    before: Any | None = None
    after: Any | None = None


class TicketHistoryOut(BaseModel):
    id: str
    ticket_id: str
    event_type: str
    action: str | None = None
    actor: str
    actor_id: str | None = None
    actor_role: str | None = None
    comment_added: bool = False
    comment_id: str | None = None
    created_at: dt.datetime
    changes: list[TicketHistoryChange] = Field(default_factory=list)


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
    mttr_global_hours: float | None = None
    mttr_p90_hours: float | None = None
    mttr_by_priority_hours: dict[str, float | None] = Field(default_factory=dict)
    mttr_by_category_hours: dict[str, float | None] = Field(default_factory=dict)
    throughput_resolved_per_week: int = 0
    backlog_open_over_days: int = 0
    backlog_threshold_days: int = 7
    reassignment_rate: float
    reassigned_tickets: int
    avg_time_to_first_action_hours: float | None
    median_time_to_first_action_hours: float | None = None
    classification_accuracy_rate: float | None
    classification_samples: int
    auto_assignment_accuracy_rate: float | None
    auto_assignment_samples: int
    auto_triage_no_correction_rate: float | None = None
    auto_triage_no_correction_count: int = 0
    auto_triage_samples: int = 0
    sla_breach_rate: float | None = None
    sla_breached_tickets: int = 0
    sla_tickets_with_due: int = 0
    first_response_sla_breach_rate: float | None = None
    first_response_sla_breached_count: int = 0
    first_response_sla_eligible: int = 0
    resolution_sla_breach_rate: float | None = None
    resolution_sla_breached_count: int = 0
    resolution_sla_eligible: int = 0
    reopen_rate: float | None = None
    first_contact_resolution_rate: float | None = None
    csat_score: float | None = None


class TicketSimilarOut(BaseModel):
    id: str
    title: str
    description: str
    status: TicketStatus
    priority: TicketPriority
    ticket_type: TicketType
    category: TicketCategory
    assignee: str
    reporter: str
    created_at: dt.datetime
    updated_at: dt.datetime
    similarity_score: float


class TicketSimilarResponse(BaseModel):
    ticket_id: str
    matches: list[TicketSimilarOut]
