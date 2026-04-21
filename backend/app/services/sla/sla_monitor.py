"""Proactive SLA monitor that promotes tickets to at-risk and notifies stakeholders."""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
from uuid import UUID

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.automation_event import AutomationEvent
from app.models.enums import TicketStatus
from app.models.notification import Notification
from app.models.ticket import Ticket
from app.services.ai.calibration import (
    PROACTIVE_SLA_AT_RISK_RATIO_THRESHOLD,
    PROACTIVE_SLA_CHECK_INTERVAL_SECONDS,
    PROACTIVE_SLA_DEDUP_WINDOW_MINUTES,
)

logger = logging.getLogger(__name__)

_OPEN_STATUSES = {
    TicketStatus.open,
    TicketStatus.in_progress,
    TicketStatus.waiting_for_customer,
    TicketStatus.waiting_for_support_vendor,
    TicketStatus.pending,
}

_monitor_task: asyncio.Task | None = None


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _elapsed_ratio(ticket: Ticket, now: dt.datetime) -> float:
    deadline = getattr(ticket, "sla_resolution_due_at", None) or getattr(ticket, "due_at", None)
    created = getattr(ticket, "created_at", None)
    if not deadline or not created:
        return 0.0
    try:
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=dt.timezone.utc)
        if created.tzinfo is None:
            created = created.replace(tzinfo=dt.timezone.utc)
        total_seconds = (deadline - created).total_seconds()
        if total_seconds <= 0:
            return 0.0
        elapsed = (now - created).total_seconds()
        return elapsed / total_seconds
    except Exception:  # noqa: BLE001
        return 0.0


def _has_recent_at_risk_notification(db: Session, ticket_id: str, now: dt.datetime) -> bool:
    try:
        window_start = now - dt.timedelta(minutes=PROACTIVE_SLA_DEDUP_WINDOW_MINUTES)
        existing = (
            db.query(Notification)
            .filter(
                Notification.event_type == "sla_at_risk",
                Notification.source == "sla_monitor",
                Notification.read_at.is_(None),
                Notification.created_at >= window_start,
                Notification.link.contains(f"/tickets/{ticket_id}"),
            )
            .first()
        )
        return existing is not None
    except Exception as exc:  # noqa: BLE001
        logger.debug("Dedup check failed for %s: %s", ticket_id, exc)
        return False


def _notify_at_risk_recipients(db: Session, *, ticket: Ticket, ratio: float) -> int:
    from app.services.notifications_service import (
        EVENT_SLA_AT_RISK,
        create_notification,
        create_notifications_for_users,
        resolve_ticket_recipients,
    )

    title = f"SLA en risque - {ticket.id}"
    body = f"Le ticket {ticket.id} a consomme {round(ratio * 100)}% de son SLA."
    metadata = {"elapsed_ratio": round(ratio, 4), "sla_status": "at_risk"}
    link = f"/tickets/{ticket.id}"

    recipients = resolve_ticket_recipients(db, ticket=ticket, include_admins=True)
    created = create_notifications_for_users(
        db=db,
        users=recipients,
        title=title,
        body=body,
        severity="high",
        link=link,
        source="sla_monitor",
        cooldown_minutes=PROACTIVE_SLA_DEDUP_WINDOW_MINUTES,
        metadata_json=metadata,
        event_type=EVENT_SLA_AT_RISK,
    )
    if created:
        return len(created)

    recipient_id = getattr(ticket, "reporter_id", None)
    if recipient_id:
        create_notification(
            db=db,
            user_id=UUID(str(recipient_id)),
            event_type=EVENT_SLA_AT_RISK,
            title=title,
            body=body,
            severity="high",
            source="sla_monitor",
            link=link,
            metadata_json={**metadata, "routing": "reporter_fallback"},
        )
        return 1
    return 0


def _record_monitor_event(
    db: Session,
    *,
    ticket_id: str,
    now: dt.datetime,
    elapsed_ratio: float,
    recipient_count: int,
) -> None:
    db.add(
        AutomationEvent(
            ticket_id=ticket_id,
            event_type="sla_at_risk_proactive",
            actor="system:sla_monitor",
            meta={
                "elapsed_ratio": round(elapsed_ratio, 4),
                "recipient_count": recipient_count,
                "routing": "resolve_ticket_recipients",
            },
            created_at=now,
        )
    )


def _run_proactive_sla_check_sync() -> None:
    db: Session = SessionLocal()
    try:
        now = _utcnow()
        candidates = (
            db.query(Ticket)
            .filter(
                Ticket.status.in_([status.value for status in _OPEN_STATUSES]),
                Ticket.sla_status == "ok",
            )
            .all()
        )

        promoted = 0
        for ticket in candidates:
            try:
                ratio = _elapsed_ratio(ticket, now)
                if ratio < PROACTIVE_SLA_AT_RISK_RATIO_THRESHOLD:
                    continue

                ticket.sla_status = "at_risk"
                ticket.updated_at = now
                db.add(ticket)

                if _has_recent_at_risk_notification(db, str(ticket.id), now):
                    continue

                recipient_count = _notify_at_risk_recipients(db, ticket=ticket, ratio=ratio)
                _record_monitor_event(
                    db,
                    ticket_id=str(ticket.id),
                    now=now,
                    elapsed_ratio=ratio,
                    recipient_count=recipient_count,
                )
                promoted += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "SLA monitor: error processing ticket %s: %s",
                    getattr(ticket, "id", "?"),
                    exc,
                )

        db.commit()
        if promoted:
            logger.info("SLA monitor: promoted %d ticket(s) to at_risk.", promoted)
    except Exception as exc:  # noqa: BLE001
        logger.error("SLA monitor run failed: %s", exc)
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
    finally:
        db.close()


async def run_proactive_sla_monitor() -> None:
    logger.info("SLA monitor: started (interval=%ds).", PROACTIVE_SLA_CHECK_INTERVAL_SECONDS)
    while True:
        try:
            await asyncio.sleep(PROACTIVE_SLA_CHECK_INTERVAL_SECONDS)
            _run_proactive_sla_check_sync()
        except asyncio.CancelledError:
            logger.info("SLA monitor: cancelled.")
            return
        except Exception as exc:  # noqa: BLE001
            logger.error("SLA monitor: unexpected error in loop: %s", exc)


async def start_sla_monitor() -> asyncio.Task:
    global _monitor_task
    _monitor_task = asyncio.create_task(run_proactive_sla_monitor())
    return _monitor_task


async def stop_sla_monitor() -> None:
    global _monitor_task
    if _monitor_task and not _monitor_task.done():
        _monitor_task.cancel()
        try:
            await _monitor_task
        except asyncio.CancelledError:
            pass
    _monitor_task = None
