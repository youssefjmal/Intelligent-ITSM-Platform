"""Snapshot cache and refresh logic for Jira KB rows."""

from __future__ import annotations

import datetime as dt
import logging
import time
from typing import Any

import httpx

from app.core.config import settings
from app.services.embeddings import invalidate_kb_search_caches
from app.services.jira_kb import state
from app.services.jira_kb.constants import LOGGER_NAME
from app.services.jira_kb.jira_fetch import _extract_issue_kb_rows, _fetch_issues_with_comments
from app.services.jira_kb.semantic import _sync_kb_chunks

logger = logging.getLogger(LOGGER_NAME)


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _store_snapshot_rows(rows: list[dict[str, str]]) -> None:
    ttl = max(30, settings.JIRA_KB_CACHE_SECONDS)
    state._snapshot_rows = list(rows)
    state._snapshot_expires_at = _utcnow() + dt.timedelta(seconds=ttl)


def refresh_jira_kb_index(*, force: bool = False) -> dict[str, Any]:
    if not settings.jira_kb_ready:
        return {
            "issues_fetched": 0,
            "issue_rows": 0,
            "comment_rows": 0,
            "chunks_written": 0,
            "embeddings_created": 0,
            "embedding_failures": 0,
            "elapsed_time_ms": 0,
            "snapshot_rows": 0,
            "jira_kb_ready": False,
        }

    if force:
        with state._snapshot_lock:
            state._snapshot_expires_at = None
            state._snapshot_rows = []
            state._kb_chunks_ready = None
            state._kb_chunks_checked_at = None

    started_at = time.monotonic()
    with httpx.Client(
        timeout=30,
        auth=(settings.JIRA_EMAIL, settings.JIRA_API_TOKEN),
        headers={"Accept": "application/json"},
    ) as client:
        issues = _fetch_issues_with_comments(client)

    issue_rows: list[dict[str, str]] = []
    comment_rows: list[dict[str, str]] = []
    for issue in issues:
        issue_row, extracted_comment_rows = _extract_issue_kb_rows(issue)
        if issue_row is not None:
            issue_rows.append(issue_row)
        comment_rows.extend(extracted_comment_rows)

    sync_metrics: dict[str, Any] = {
        "chunks_written": 0,
        "embeddings_created": 0,
        "embedding_failures": 0,
        "budget_exhausted": False,
        "passes": 0,
    }
    if issue_rows or comment_rows:
        max_passes = 2
        for pass_index in range(1, max_passes + 1):
            cycle_chunks_written = 0
            cycle_budget_exhausted = False
            sync_batches = [
                {"issue_rows": issue_rows, "comment_rows": []},
                {"issue_rows": [], "comment_rows": comment_rows},
            ]
            for batch in sync_batches:
                if not batch["issue_rows"] and not batch["comment_rows"]:
                    continue
                try:
                    pass_metrics = _sync_kb_chunks(
                        issue_rows=batch["issue_rows"],
                        comment_rows=batch["comment_rows"],
                    )
                except Exception as exc:
                    logger.warning("Jira KB semantic chunk sync failed: %s", exc)
                    cycle_budget_exhausted = False
                    cycle_chunks_written = 0
                    break

                written = int(pass_metrics.get("chunks_written") or 0)
                sync_metrics["chunks_written"] += written
                sync_metrics["embeddings_created"] += int(pass_metrics.get("embeddings_created") or 0)
                sync_metrics["embedding_failures"] += int(pass_metrics.get("embedding_failures") or 0)
                cycle_chunks_written += written
                cycle_budget_exhausted = cycle_budget_exhausted or bool(pass_metrics.get("budget_exhausted"))
            sync_metrics["budget_exhausted"] = cycle_budget_exhausted
            sync_metrics["passes"] = pass_index
            if cycle_chunks_written == 0 or not cycle_budget_exhausted:
                break
    invalidate_kb_search_caches()

    with state._snapshot_lock:
        _store_snapshot_rows(comment_rows)

    metrics = {
        "issues_fetched": len(issues),
        "issue_rows": len(issue_rows),
        "comment_rows": len(comment_rows),
        "chunks_written": int(sync_metrics.get("chunks_written") or 0),
        "embeddings_created": int(sync_metrics.get("embeddings_created") or 0),
        "embedding_failures": int(sync_metrics.get("embedding_failures") or 0),
        "passes": int(sync_metrics.get("passes") or 0),
        "elapsed_time_ms": int((time.monotonic() - started_at) * 1000),
        "snapshot_rows": len(comment_rows),
        "jira_kb_ready": True,
    }
    logger.info(
        "Jira KB refresh complete: issues_fetched=%s chunks_written=%s embeddings_created=%s failures=%s elapsed_ms=%s",
        metrics["issues_fetched"],
        metrics["chunks_written"],
        metrics["embeddings_created"],
        metrics["embedding_failures"],
        metrics["elapsed_time_ms"],
    )
    return metrics


def _fetch_kb_snapshot() -> list[dict[str, str]]:
    refresh_jira_kb_index()
    with state._snapshot_lock:
        return list(state._snapshot_rows)


def _get_snapshot() -> list[dict[str, str]]:
    if not settings.jira_kb_ready:
        return []

    now = _utcnow()
    with state._snapshot_lock:
        if state._snapshot_expires_at and now < state._snapshot_expires_at:
            return list(state._snapshot_rows)

        existing = list(state._snapshot_rows)
        try:
            refresh_jira_kb_index()
        except Exception as exc:
            logger.warning("Jira KB sync failed: %s", exc)
            if existing:
                state._snapshot_expires_at = now + dt.timedelta(seconds=60)
                return existing
            return []

        return list(state._snapshot_rows)
