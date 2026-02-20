"""Snapshot cache and refresh logic for Jira KB rows."""

from __future__ import annotations

import datetime as dt
import logging

import httpx

from app.core.config import settings
from app.services.jira_kb import state
from app.services.jira_kb.constants import LOGGER_NAME
from app.services.jira_kb.jira_fetch import _extract_issue_kb_rows, _fetch_issues_with_comments
from app.services.jira_kb.semantic import _sync_kb_chunks

logger = logging.getLogger(LOGGER_NAME)


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _fetch_kb_snapshot() -> list[dict[str, str]]:
    if not settings.jira_kb_ready:
        return []

    with httpx.Client(
        timeout=30,
        auth=(settings.JIRA_EMAIL, settings.JIRA_API_TOKEN),
        headers={"Accept": "application/json"},
    ) as client:
        issues = _fetch_issues_with_comments(client)

    issue_rows: list[dict[str, str]] = []
    rows: list[dict[str, str]] = []
    for issue in issues:
        issue_row, comment_rows = _extract_issue_kb_rows(issue)
        if issue_row is not None:
            issue_rows.append(issue_row)
        rows.extend(comment_rows)

    if issue_rows or rows:
        try:
            _sync_kb_chunks(issue_rows=issue_rows, comment_rows=rows)
        except Exception as exc:
            logger.warning("Jira KB semantic chunk sync failed: %s", exc)
    return rows


def _get_snapshot() -> list[dict[str, str]]:
    if not settings.jira_kb_ready:
        return []

    now = _utcnow()
    with state._snapshot_lock:
        if state._snapshot_expires_at and now < state._snapshot_expires_at and state._snapshot_rows:
            return list(state._snapshot_rows)

        existing = list(state._snapshot_rows)
        try:
            fresh = _fetch_kb_snapshot()
        except Exception as exc:
            logger.warning("Jira KB sync failed: %s", exc)
            if existing:
                state._snapshot_expires_at = now + dt.timedelta(seconds=60)
                return existing
            return []

        state._snapshot_rows = fresh
        ttl = max(30, settings.JIRA_KB_CACHE_SECONDS)
        state._snapshot_expires_at = now + dt.timedelta(seconds=ttl)
        return list(state._snapshot_rows)
