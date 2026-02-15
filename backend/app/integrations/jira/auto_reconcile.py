"""Background Jira reconcile loop for automatic inbound sync."""

from __future__ import annotations

import asyncio
import logging

from app.core.config import settings
from app.db.session import SessionLocal
from app.integrations.jira.schemas import JiraReconcileRequest
from app.integrations.jira.service import reconcile

logger = logging.getLogger(__name__)

_task: asyncio.Task | None = None


def _jira_ready() -> bool:
    return bool(
        settings.JIRA_BASE_URL.strip()
        and settings.JIRA_EMAIL.strip()
        and settings.JIRA_API_TOKEN.strip()
    )


def _run_once() -> None:
    if not _jira_ready():
        logger.debug("Skipping Jira auto reconcile: Jira credentials are not configured")
        return

    db = SessionLocal()
    try:
        payload = JiraReconcileRequest(
            project_key=(settings.JIRA_PROJECT_KEY or "").strip() or None,
            lookback_days=max(1, min(3650, settings.JIRA_AUTO_RECONCILE_LOOKBACK_DAYS)),
        )
        result = reconcile(db, payload)
        logger.info(
            "Jira auto reconcile completed: project=%s issues=%s tickets=%s comments=%s updated_comments=%s errors=%s",
            result.project_key,
            result.issues_seen,
            result.tickets_upserted,
            result.comments_upserted,
            result.comments_updated,
            len(result.errors),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Jira auto reconcile failed: %s", exc)
    finally:
        db.close()


async def _loop() -> None:
    startup_delay = max(0, settings.JIRA_AUTO_RECONCILE_STARTUP_DELAY_SECONDS)
    interval = max(30, settings.JIRA_AUTO_RECONCILE_INTERVAL_SECONDS)
    if startup_delay:
        await asyncio.sleep(startup_delay)
    while True:
        await asyncio.to_thread(_run_once)
        await asyncio.sleep(interval)


async def start_jira_auto_reconcile() -> None:
    global _task
    if _task is not None:
        return
    if not settings.JIRA_AUTO_RECONCILE_ENABLED:
        return
    _task = asyncio.create_task(_loop(), name="jira-auto-reconcile")
    logger.info("Jira auto reconcile loop started (every %s seconds)", max(30, settings.JIRA_AUTO_RECONCILE_INTERVAL_SECONDS))


async def stop_jira_auto_reconcile() -> None:
    global _task
    task = _task
    _task = None
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
