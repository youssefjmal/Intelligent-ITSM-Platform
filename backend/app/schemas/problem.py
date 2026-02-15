"""Pydantic schemas for problem management."""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.core.sanitize import clean_multiline, clean_single_line
from app.models.enums import ProblemStatus, TicketCategory


class ProblemTicketOut(BaseModel):
    id: str
    title: str
    status: str
    assignee: str
    reporter: str
    created_at: dt.datetime
    updated_at: dt.datetime

    class Config:
        from_attributes = True


class ProblemOut(BaseModel):
    id: str
    title: str
    category: TicketCategory
    status: ProblemStatus
    created_at: dt.datetime
    updated_at: dt.datetime
    last_seen_at: dt.datetime | None
    resolved_at: dt.datetime | None
    occurrences_count: int
    active_count: int
    root_cause: str | None
    workaround: str | None
    permanent_fix: str | None
    similarity_key: str
    assignee: str | None = None

    class Config:
        from_attributes = True


class ProblemDetailOut(ProblemOut):
    tickets: list[ProblemTicketOut]
    ai_suggestions: list[str] = Field(default_factory=list)


class ProblemDetectRequest(BaseModel):
    window_days: int = Field(default=3, ge=1, le=90)
    min_count: int = Field(default=5, ge=2, le=100)


class ProblemDetectResponse(BaseModel):
    processed_groups: int
    created: int
    updated: int
    linked: int


class ProblemUpdate(BaseModel):
    status: ProblemStatus | None = None
    root_cause: str | None = Field(default=None, max_length=5000)
    workaround: str | None = Field(default=None, max_length=5000)
    permanent_fix: str | None = Field(default=None, max_length=5000)
    resolution_comment: str | None = Field(default=None, max_length=1200)

    @field_validator("root_cause", "workaround", "permanent_fix", mode="before")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        cleaned = clean_multiline(value)
        return cleaned or None

    @field_validator("resolution_comment", mode="before")
    @classmethod
    def normalize_resolution_comment(cls, value: str | None) -> str | None:
        cleaned = clean_single_line(value)
        return cleaned or None


class ProblemLinkResponse(BaseModel):
    problem_id: str
    ticket_id: str
    linked: bool


class ResolveLinkedTicketsRequest(BaseModel):
    confirm: bool = False
    resolution_comment: str = Field(
        ...,
        min_length=5,
        max_length=1200,
    )

    @field_validator("resolution_comment", mode="before")
    @classmethod
    def normalize_comment(cls, value: str) -> str:
        return clean_single_line(value)


class ResolveLinkedTicketsResponse(BaseModel):
    problem_id: str
    resolved_count: int


class ProblemAISuggestionItem(BaseModel):
    text: str
    confidence: int = Field(ge=0, le=100)


class ProblemAISuggestionsOut(BaseModel):
    problem_id: str
    category: TicketCategory
    assignee: str | None = None
    suggestions: list[str]
    suggestions_scored: list[ProblemAISuggestionItem] = Field(default_factory=list)
    root_cause_suggestion: str | None = None
    workaround_suggestion: str | None = None
    permanent_fix_suggestion: str | None = None
    root_cause_confidence: int | None = Field(default=None, ge=0, le=100)
    workaround_confidence: int | None = Field(default=None, ge=0, le=100)
    permanent_fix_confidence: int | None = Field(default=None, ge=0, le=100)


class ProblemAssigneeUpdateRequest(BaseModel):
    mode: Literal["auto", "manual"] = "manual"
    assignee: str | None = Field(default=None, min_length=2, max_length=80)

    @field_validator("assignee", mode="before")
    @classmethod
    def normalize_assignee(cls, value: str | None) -> str | None:
        cleaned = clean_single_line(value)
        return cleaned or None


class ProblemAssigneeUpdateResponse(BaseModel):
    problem_id: str
    assignee: str
    updated_tickets: int
    mode: Literal["auto", "manual"]
