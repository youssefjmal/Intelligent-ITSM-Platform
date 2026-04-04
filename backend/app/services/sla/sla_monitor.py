"""Proactive SLA monitor — background task that fires at_risk notifications."""

from __future__ import annotations

import asyncio
import datetime as dt
import logging

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
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
    """Return timezone-aware UTC now."""
    return dt.datetime.now(dt.timezone.utc)


def _elapsed_ratio(ticket: Ticket, now: dt.datetime) -> float:
    """
    Compute the fraction of SLA time consumed for a ticket.

    Args:
        ticket: Ticket ORM object.
        now: Current UTC datetime.

    Returns:
        Float 0.0 to 1.0+. Returns 0.0 if SLA deadline not set.
        May exceed 1.0 if the ticket has already breached its SLA.
    """
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
    """
    Check if an unread at_risk notification was already created recently.

    Args:
        db: Database session.
        ticket_id: ID of the ticket to check.
        now: Current UTC datetime.

    Returns:
        True if a recent unread sla_at_risk notification exists for this ticket.
        False on any DB error (safe — allows creating notification).
    """
    try:
        window_start = now - dt.timedelta(minutes=PROACTIVE_SLA_DEDUP_WINDOW_MINUTES)
        existing = (
            db.query(Notification)
            .filter(
                Notification.event_type == "sla_at_risk",
                Notification.source == "sla_monitor",
                Notification.read_at.is_(None),
                Notification.created_at >= window_start,
                # Use the link field to match by ticket_id since the Notification
                # model stores the entity reference in link (/tickets/{id})
                Notification.link.contains(f"/tickets/{ticket_id}"),
            )
            .first()
        )
        return existing is not None
    except Exception as exc:  # noqa: BLE001
        logger.debug("Dedup check failed for %s: %s", ticket_id, exc)
        return False


def _run_proactive_sla_check_sync() -> None:
    """
    Synchronous inner loop for proactive SLA monitoring.

    Opens its own DB session, checks all eligible tickets, creates
    notifications and automation events as needed, then closes the session.

    Does NOT raise — all exceptions are caught and logged.
    """
    db: Session = SessionLocal()
    try:
        now = _utcnow()
        at_risk_threshold = PROACTIVE_SLA_AT_RISK_RATIO_THRESHOLD

        # Query open tickets with sla_status still "ok" (not yet escalated)
        candidates = (
            db.query(Ticket)
            .filter(
                Ticket.status.in_([s.value for s in _OPEN_STATUSES]),
                Ticket.sla_status == "ok",
            )
            .all()
        )

        promoted = 0
        for ticket in candidates:
            try:
                ratio = _elapsed_ratio(ticket, now)
                if ratio < at_risk_threshold:
                    continue

                # Update sla_status to at_risk
                ticket.sla_status = "at_risk"
                ticket.updated_at = now
                db.add(ticket)

                # Skip if recent dedup notification exists
                if _has_recent_at_risk_notification(db, str(ticket.id), now):
                    continue

                # Import here to avoid circular imports at module level
                from app.services.notifications_service import (
                    EVENT_SLA_AT_RISK,
                    create_notification,
                )

                # Ticket.assignee is a string name, not a foreign key.
                # Use reporter_id to find the user to notify.
                recipient_id = getattr(ticket, "reporter_id", None)
                if recipient_id:
                    try:
                        from uuid import UUID
                        create_notification(
                            db=db,
                            user_id=UUID(str(recipient_id)),
                            event_type=EVENT_SLA_AT_RISK,
                            title=f"SLA en risque — {ticket.id}",
                            body=f"Le ticket {ticket.id} a consommé {round(ratio * 100)}% de son SLA.",
                            severity="high",
                            source="sla_monitor",
                            link=f"/tickets/{ticket.id}",
                            metadata_json={"elapsed_ratio": round(ratio, 4), "sla_status": "at_risk"},
                        )
                    except Exception as notif_exc:  # noqa: BLE001
                        logger.warning(
                            "SLA monitor: notification failed for ticket %s: %s",
                            ticket.id,
                            notif_exc,
                        )

                # Log automation event
                try:
                    from app.models.automation_event import AutomationEvent

                    event = AutomationEvent(
                        ticket_id=str(ticket.id),
                        event_type="sla_at_risk_proactive",
                        actor="system:sla_monitor",
                        meta={"elapsed_ratio": round(ratio, 4)},
                        created_at=now,
                    )
                    db.add(event)
                except Exception:  # noqa: BLE001
                    pass  # AutomationEvent may not exist — non-critical

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
    """
    Background task that monitors SLA state and fires notifications
    proactively when tickets cross the at_risk threshold.

    Runs every PROACTIVE_SLA_CHECK_INTERVAL_SECONDS seconds.
    Does NOT replace the existing batch SLA run — it is additive.

    Logic:
    1. Fetch all open/in-progress tickets with sla_status = "ok"
       and elapsed_ratio >= PROACTIVE_SLA_AT_RISK_RATIO_THRESHOLD
    2. For each: update sla_status to "at_risk" in the DB
    3. Create an in-app notification via notifications_service
       with severity="high" and source="sla_monitor"
    4. Log to automation_events with actor="system:sla_monitor"
    5. Skip tickets that already have an unread "sla_at_risk" notification
       created within PROACTIVE_SLA_DEDUP_WINDOW_MINUTES

    Duplicate suppression:
    Before creating a notification, check notifications table for
    an existing unread notification for this ticket with source="sla_monitor"
    created within the last PROACTIVE_SLA_DEDUP_WINDOW_MINUTES minutes.

    Never raises — all exceptions are caught internally.
    """
    logger.info(
        "SLA monitor: started (interval=%ds).", PROACTIVE_SLA_CHECK_INTERVAL_SECONDS
    )
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
    """
    Start the proactive SLA monitor as an asyncio background task.

    Returns:
        The running asyncio.Task. Store a reference to prevent garbage collection.
    """
    global _monitor_task
    _monitor_task = asyncio.create_task(run_proactive_sla_monitor())
    return _monitor_task


async def stop_sla_monitor() -> None:
    """
    Stop the proactive SLA monitor background task gracefully.

    Cancels the task and waits for it to finish.
    Safe to call even if the monitor was never started.
    """
    global _monitor_task
    if _monitor_task and not _monitor_task.done():
        _monitor_task.cancel()
        try:
            await _monitor_task
        except asyncio.CancelledError:
            pass
    _monitor_task = None
