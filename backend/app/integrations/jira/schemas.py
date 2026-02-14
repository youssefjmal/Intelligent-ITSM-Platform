"""DTOs for Jira integration endpoints."""

from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import BaseModel, Field


class JiraUpsertResult(BaseModel):
    status: str = "ok"
    jira_key: str
    created: bool
    updated: bool


class JiraReconcileRequest(BaseModel):
    since: dt.datetime | None = None
    project_key: str | None = Field(default=None, max_length=32)


class JiraReconcileResult(BaseModel):
    status: str = "ok"
    project_key: str
    since: dt.datetime | None = None
    fetched: int
    created: int
    updated: int
    unchanged: int
    errors: list[str] = Field(default_factory=list)


class JiraUpsertRequest(BaseModel):
    issueKey: str | None = None
    issue: dict[str, Any] | None = None
    fields: dict[str, Any] | None = None
    comments: list[dict[str, Any]] | None = None
    raw_payload: dict[str, Any] | None = None
