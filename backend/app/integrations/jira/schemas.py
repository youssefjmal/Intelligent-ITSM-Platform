"""DTOs for Jira reverse-sync endpoints."""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, Field


class JiraWebhookResponse(BaseModel):
    status: str = "ok"
    issue_key: str
    tickets_upserted: int = 0
    comments_upserted: int = 0
    comments_updated: int = 0
    skipped: int = 0


class JiraReconcileRequest(BaseModel):
    project_key: str | None = Field(default=None, max_length=32)
    lookback_days: int = Field(default=30, ge=1, le=3650)


class JiraReconcileResult(BaseModel):
    status: str = "ok"
    project_key: str
    since: dt.datetime
    last_synced_at: dt.datetime | None = None
    issues_seen: int = 0
    pages: int = 0
    tickets_upserted: int = 0
    comments_upserted: int = 0
    comments_updated: int = 0
    skipped: int = 0
    errors: list[str] = Field(default_factory=list)
