"""SLA debug endpoints."""

from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import APIRouter, Body, Depends, Path
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.exceptions import BadRequestError, InsufficientPermissionsError, NotFoundError
from app.core.rate_limit import rate_limit
from app.db.session import get_db
from app.integrations.jira.sla_sync import sync_ticket_sla
from app.models.enums import TicketStatus, UserRole
from app.models.ticket import Ticket
from app.models.user import User
from app.services.sla.auto_escalation import apply_escalation

router = APIRouter(dependencies=[Depends(rate_limit()), Depends(get_current_user)])

_DEFAULT_BATCH_LIMIT = 200
_DEFAULT_MAX_AGE_MINUTES = 10
_MAX_FAILURES = 20
_MAX_ESCALATIONS = 50
_DEFAULT_BATCH_STATUSES = (
    TicketStatus.open,
    TicketStatus.in_progress,
    TicketStatus.waiting_for_customer,
    TicketStatus.waiting_for_support_vendor,
    TicketStatus.pending,
)
_STATUS_ALIASES = {
    "open": TicketStatus.open,
    "in_progress": TicketStatus.in_progress,
    "waiting_for_customer": TicketStatus.waiting_for_customer,
    "waiting_for_support": TicketStatus.waiting_for_support_vendor,
    "waiting_for_vendor": TicketStatus.waiting_for_support_vendor,
    "waiting_for_support_vendor": TicketStatus.waiting_for_support_vendor,
    "pending": TicketStatus.pending,
    "resolved": TicketStatus.resolved,
    "closed": TicketStatus.closed,
}


class SLABatchRunRequest(BaseModel):
    limit: int = Field(default=_DEFAULT_BATCH_LIMIT, ge=1)
    status: list[str] | None = None
    force: bool = False
    max_age_minutes: int = Field(default=_DEFAULT_MAX_AGE_MINUTES, ge=1)


def _as_utc(value: dt.datetime | None) -> dt.datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(dt.timezone.utc)


def _iso(value: dt.datetime | None) -> str | None:
    normalized = _as_utc(value)
    if normalized is None:
        return None
    return normalized.isoformat()


def _status_value(status: Any) -> str:
    value = status.value if hasattr(status, "value") else status
    return str(value or "").strip().lower()


def _priority_value(priority: Any) -> str:
    value = priority.value if hasattr(priority, "value") else priority
    return str(value or "").strip().lower()


def _normalize_status_token(raw: str) -> str:
    token = str(raw or "").strip().lower()
    return token.replace("-", "_").replace(" ", "_")


def _resolve_status_filters(raw_statuses: list[str] | None) -> list[TicketStatus]:
    if raw_statuses is None:
        return list(_DEFAULT_BATCH_STATUSES)

    resolved: list[TicketStatus] = []
    seen: set[TicketStatus] = set()
    for raw in raw_statuses:
        token = _normalize_status_token(raw)
        if not token:
            continue
        status = _STATUS_ALIASES.get(token)
        if status is None:
            raise BadRequestError("invalid_status_filter", details={"status": raw})
        if status in seen:
            continue
        seen.add(status)
        resolved.append(status)
    if not resolved:
        raise BadRequestError("invalid_status_filter", details={"status": raw_statuses})
    return resolved


def _is_recent_sync(value: dt.datetime | None, *, cutoff: dt.datetime) -> bool:
    synced_at = _as_utc(value)
    cutoff_utc = _as_utc(cutoff)
    if synced_at is None or cutoff_utc is None:
        return False
    return synced_at > cutoff_utc


def _is_ticket_eligible(
    ticket: Ticket,
    *,
    allowed_status_values: set[str],
    force: bool,
    stale_before: dt.datetime,
) -> tuple[bool, str | None]:
    jira_key = str(ticket.jira_key or "").strip()
    if not jira_key:
        return False, "missing_jira_key"

    if _status_value(ticket.status) not in allowed_status_values:
        return False, "status_filtered"

    if not force and _is_recent_sync(ticket.sla_last_synced_at, cutoff=stale_before):
        return False, "too_recent"

    return True, None


def _sync_succeeded(*, before: dt.datetime | None, after: dt.datetime | None, sync_result: bool) -> bool:
    if sync_result:
        return True
    before_utc = _as_utc(before)
    after_utc = _as_utc(after)
    if after_utc is None:
        return False
    if before_utc is None:
        return True
    return after_utc > before_utc


def _serialize_escalation(ticket: Ticket, *, from_priority: str) -> dict[str, str]:
    return {
        "ticket_id": ticket.id,
        "jira_key": str(ticket.jira_key or ""),
        "from": from_priority,
        "to": _priority_value(ticket.priority),
        "reason": str(ticket.priority_escalation_reason or ""),
    }


def _snapshot(ticket: Ticket) -> dict[str, Any]:
    return {
        "ticket_id": ticket.id,
        "jira_key": ticket.jira_key,
        "priority": ticket.priority.value,
        "sla_status": ticket.sla_status or "unknown",
        "sla_first_response_due_at": _iso(ticket.sla_first_response_due_at),
        "sla_resolution_due_at": _iso(ticket.sla_resolution_due_at),
        "sla_first_response_breached": bool(ticket.sla_first_response_breached),
        "sla_resolution_breached": bool(ticket.sla_resolution_breached),
        "sla_first_response_completed_at": _iso(ticket.sla_first_response_completed_at),
        "sla_resolution_completed_at": _iso(ticket.sla_resolution_completed_at),
        "sla_remaining_minutes": ticket.sla_remaining_minutes,
        "sla_elapsed_minutes": ticket.sla_elapsed_minutes,
        "sla_last_synced_at": _iso(ticket.sla_last_synced_at),
        "priority_auto_escalated": bool(ticket.priority_auto_escalated),
        "priority_escalation_reason": ticket.priority_escalation_reason,
        "priority_escalated_at": _iso(ticket.priority_escalated_at),
    }


@router.get("/ticket/{ticket_id}")
def get_ticket_sla_snapshot(
    ticket_id: str = Path(..., min_length=3, max_length=32),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    ticket = db.get(Ticket, ticket_id)
    if not ticket:
        raise NotFoundError("ticket_not_found", details={"ticket_id": ticket_id})
    return _snapshot(ticket)


@router.post("/ticket/{ticket_id}/sync")
def sync_ticket_sla_snapshot(
    ticket_id: str = Path(..., min_length=3, max_length=32),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    if current_user.role not in {UserRole.admin, UserRole.agent}:
        raise InsufficientPermissionsError("forbidden")

    ticket = db.get(Ticket, ticket_id)
    if not ticket:
        raise NotFoundError("ticket_not_found", details={"ticket_id": ticket_id})
    if not ticket.jira_key:
        raise BadRequestError("ticket_missing_jira_key", details={"ticket_id": ticket_id})

    try:
        sync_ticket_sla(db, ticket, ticket.jira_key)
        apply_escalation(db, ticket, actor=f"user:{current_user.id}")
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        raise BadRequestError("sla_sync_failed", details={"ticket_id": ticket_id, "error": str(exc)})

    db.refresh(ticket)
    return _snapshot(ticket)


@router.post("/run")
def run_sla_batch(
    payload: SLABatchRunRequest | None = Body(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    if current_user.role not in {UserRole.admin, UserRole.agent}:
        raise InsufficientPermissionsError("forbidden")

    params = payload or SLABatchRunRequest()
    status_filters = _resolve_status_filters(params.status)
    allowed_status_values = {status.value for status in status_filters}
    stale_before = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=params.max_age_minutes)

    ticket_ids = list(
        db.execute(
            select(Ticket.id)
            .where(
                Ticket.jira_key.is_not(None),
                Ticket.jira_key != "",
                Ticket.status.in_(status_filters),
            )
            .order_by(Ticket.sla_last_synced_at.asc().nullsfirst(), Ticket.updated_at.desc())
            .limit(params.limit)
        ).scalars().all()
    )

    result: dict[str, Any] = {
        "processed": 0,
        "synced": 0,
        "escalated": 0,
        "skipped": 0,
        "failed": 0,
        "failures": [],
        "escalations": [],
    }

    for ticket_id in ticket_ids:
        result["processed"] += 1
        ticket = db.get(Ticket, ticket_id)
        if not ticket:
            result["skipped"] += 1
            continue

        eligible, _ = _is_ticket_eligible(
            ticket,
            allowed_status_values=allowed_status_values,
            force=params.force,
            stale_before=stale_before,
        )
        if not eligible:
            result["skipped"] += 1
            continue

        jira_key = str(ticket.jira_key or "").strip()
        before_synced_at = ticket.sla_last_synced_at
        from_priority = _priority_value(ticket.priority)

        sync_ok = False
        escalated_now = False
        escalation_data: dict[str, str] | None = None
        processing_error: str | None = None

        try:
            sync_result = sync_ticket_sla(db, ticket, jira_key)
            sync_ok = _sync_succeeded(before=before_synced_at, after=ticket.sla_last_synced_at, sync_result=sync_result)
            escalated_now = apply_escalation(db, ticket, actor="system:n8n")
            if escalated_now:
                escalation_data = _serialize_escalation(ticket, from_priority=from_priority)
            db.commit()
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            processing_error = str(exc)

        if processing_error is not None:
            result["failed"] += 1
            if len(result["failures"]) < _MAX_FAILURES:
                result["failures"].append(
                    {
                        "ticket_id": ticket.id,
                        "jira_key": jira_key,
                        "error": processing_error,
                    }
                )
            continue

        if sync_ok:
            result["synced"] += 1
        else:
            result["failed"] += 1
            if len(result["failures"]) < _MAX_FAILURES:
                result["failures"].append(
                    {
                        "ticket_id": ticket.id,
                        "jira_key": jira_key,
                        "error": "sla_sync_failed",
                    }
                )

        if escalated_now:
            result["escalated"] += 1
            if escalation_data is not None and len(result["escalations"]) < _MAX_ESCALATIONS:
                result["escalations"].append(escalation_data)

    return result
