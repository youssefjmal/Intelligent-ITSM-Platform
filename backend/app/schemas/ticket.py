"""Pydantic schemas for tickets, comments, and analytics."""

from __future__ import annotations

import datetime as dt
from pydantic import BaseModel

from app.models.enums import TicketCategory, TicketPriority, TicketStatus


class TicketCommentOut(BaseModel):
    id: str
    author: str
    content: str
    created_at: dt.datetime

    class Config:
        from_attributes = True


class TicketBase(BaseModel):
    title: str
    description: str
    priority: TicketPriority
    category: TicketCategory
    assignee: str
    reporter: str
    tags: list[str]


class TicketCreate(TicketBase):
    pass


class TicketStatusUpdate(BaseModel):
    status: TicketStatus


class TicketOut(TicketBase):
    id: str
    status: TicketStatus
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
