"""Auto-escalation decisions based only on Jira SLA state."""

from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy.orm import Session

from app.models.enums import TicketPriority, TicketStatus
from app.models.ticket import Ticket

logger = logging.getLogger(__name__)

_ESCALATION_COOLDOWN = dt.timedelta(hours=6)
_PRIORITY_RANK = {
    TicketPriority.low: 0,
    TicketPriority.medium: 1,
    TicketPriority.high: 2,
    TicketPriority.critical: 3,
}


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _as_utc(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(dt.timezone.utc)


def _is_higher(candidate: TicketPriority, current: TicketPriority) -> bool:
    return _PRIORITY_RANK.get(candidate, -1) > _PRIORITY_RANK.get(current, -1)


def _one_step_higher(priority: TicketPriority) -> TicketPriority:
    if priority == TicketPriority.low:
        return TicketPriority.medium
    if priority == TicketPriority.medium:
        return TicketPriority.high
    if priority == TicketPriority.high:
        return TicketPriority.critical
    return TicketPriority.critical


def compute_escalation(ticket: Ticket) -> tuple[TicketPriority | None, str | None]:
    """Return the escalated priority (if any) and reason."""
    if ticket.status in {TicketStatus.resolved, TicketStatus.closed}:
        return None, None

    current = ticket.priority
    target: TicketPriority | None = None
    reason: str | None = None

    if bool(ticket.sla_resolution_breached):
        target = TicketPriority.critical
        reason = "jira_sla_resolution_breached"
    elif bool(ticket.sla_first_response_breached):
        if _PRIORITY_RANK[current] < _PRIORITY_RANK[TicketPriority.high]:
            target = TicketPriority.high
            reason = "jira_sla_first_response_breached"
    else:
        remaining = ticket.sla_remaining_minutes
        if remaining is not None:
            if remaining <= 10 and _PRIORITY_RANK[current] < _PRIORITY_RANK[TicketPriority.high]:
                target = TicketPriority.high
                reason = "jira_sla_remaining_le_10m"
            elif remaining <= 30:
                stepped = _one_step_higher(current)
                if _is_higher(stepped, current):
                    target = stepped
                    reason = "jira_sla_remaining_le_30m"

    if target is None or not _is_higher(target, current):
        return None, None
    return target, reason


def apply_escalation(db: Session, ticket: Ticket, actor: str = "system") -> bool:
    """Apply escalation in-place. Caller is responsible for commit."""
    target, reason = compute_escalation(ticket)
    if target is None:
        return False

    now = _utcnow()
    if ticket.priority_escalated_at is not None:
        last = _as_utc(ticket.priority_escalated_at)
        if now - last < _ESCALATION_COOLDOWN:
            return False

    ticket.priority = target
    ticket.priority_auto_escalated = True
    ticket.priority_escalation_reason = reason or f"jira_sla_escalated_by_{actor}"
    ticket.priority_escalated_at = now
    ticket.updated_at = now
    db.add(ticket)
    db.flush()
    logger.info("Auto-escalated ticket %s to %s (%s)", ticket.id, target.value, ticket.priority_escalation_reason)
    return True

