"""Helpers to serialize tickets safely for API responses."""

from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import ValidationError

from app.core.sanitize import clean_multiline, clean_single_line
from app.models.enums import TicketCategory, TicketPriority, TicketStatus, TicketType
from app.schemas.ticket import (
    MAX_DESCRIPTION_LEN,
    MAX_NAME_LEN,
    MAX_TITLE_LEN,
    TicketCommentOut,
    TicketOut,
)

def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _normalize_datetime(value: Any) -> dt.datetime:
    if isinstance(value, dt.datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=dt.timezone.utc)
        return value.astimezone(dt.timezone.utc)
    return _utcnow()


def _normalize_title(value: Any, *, ticket_id: str) -> str:
    cleaned = clean_single_line(str(value or ""))[:MAX_TITLE_LEN]
    if len(cleaned) >= 3:
        return cleaned
    fallback = clean_single_line(f"Ticket {ticket_id}")[:MAX_TITLE_LEN]
    return fallback if len(fallback) >= 3 else "Ticket"


def _normalize_description(value: Any, *, title: str, ticket_id: str) -> str:
    cleaned = clean_multiline(str(value or ""))[:MAX_DESCRIPTION_LEN]
    if len(cleaned) >= 5:
        return cleaned

    summary_fallback = clean_multiline(title)[:MAX_DESCRIPTION_LEN]
    if len(summary_fallback) >= 5:
        return summary_fallback

    generated = clean_multiline(f"Ticket {ticket_id} details unavailable.")[:MAX_DESCRIPTION_LEN]
    return generated if len(generated) >= 5 else "Ticket details unavailable."


def _normalize_name(value: Any, *, fallback: str) -> str:
    cleaned = clean_single_line(str(value or ""))[:MAX_NAME_LEN]
    if len(cleaned) >= 2:
        return cleaned
    fallback_clean = clean_single_line(fallback)[:MAX_NAME_LEN]
    return fallback_clean if len(fallback_clean) >= 2 else fallback


def _normalize_tags(values: Any) -> list[str]:
    raw_values = values if isinstance(values, list) else list(values or [])
    normalized: list[str] = []
    seen: set[str] = set()
    for item in raw_values:
        cleaned = clean_single_line(str(item or ""))[:32]
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(cleaned)
        if len(normalized) >= 10:
            break
    return normalized


def _normalize_optional_enum(value: Any, enum_type):  # noqa: ANN001
    if value is None or value == "":
        return None
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except Exception:
        return None


def _serialize_comment(comment: Any) -> TicketCommentOut:
    payload = {
        "id": str(getattr(comment, "id", "") or ""),
        "author": _normalize_name(getattr(comment, "author", None), fallback="Unknown"),
        "content": clean_multiline(str(getattr(comment, "content", "") or "")) or "-",
        "created_at": _normalize_datetime(getattr(comment, "created_at", None)),
    }
    return TicketCommentOut.model_validate(payload)


def _sanitized_ticket_payload(ticket: Any) -> dict[str, Any]:
    ticket_id = str(getattr(ticket, "id", "") or "UNKNOWN")
    title = _normalize_title(getattr(ticket, "title", None), ticket_id=ticket_id)
    comments = [_serialize_comment(comment) for comment in list(getattr(ticket, "comments", []) or [])]
    return {
        "id": ticket_id,
        "problem_id": getattr(ticket, "problem_id", None),
        "title": title,
        "description": _normalize_description(getattr(ticket, "description", None), title=title, ticket_id=ticket_id),
        "status": getattr(ticket, "status", TicketStatus.open) or TicketStatus.open,
        "priority": getattr(ticket, "priority", TicketPriority.medium) or TicketPriority.medium,
        "ticket_type": getattr(ticket, "ticket_type", TicketType.service_request) or TicketType.service_request,
        "category": getattr(ticket, "category", TicketCategory.service_request) or TicketCategory.service_request,
        "assignee": _normalize_name(getattr(ticket, "assignee", None), fallback="Unassigned"),
        "reporter": _normalize_name(getattr(ticket, "reporter", None), fallback="Jira"),
        "auto_assignment_applied": bool(getattr(ticket, "auto_assignment_applied", False)),
        "auto_priority_applied": bool(getattr(ticket, "auto_priority_applied", False)),
        "assignment_model_version": clean_single_line(str(getattr(ticket, "assignment_model_version", "") or "")) or "legacy",
        "priority_model_version": clean_single_line(str(getattr(ticket, "priority_model_version", "") or "")) or "legacy",
        "predicted_priority": _normalize_optional_enum(getattr(ticket, "predicted_priority", None), TicketPriority),
        "predicted_ticket_type": _normalize_optional_enum(getattr(ticket, "predicted_ticket_type", None), TicketType),
        "predicted_category": _normalize_optional_enum(getattr(ticket, "predicted_category", None), TicketCategory),
        "assignment_change_count": int(getattr(ticket, "assignment_change_count", 0) or 0),
        "first_action_at": getattr(ticket, "first_action_at", None),
        "resolved_at": getattr(ticket, "resolved_at", None),
        "due_at": getattr(ticket, "due_at", None),
        "sla_status": getattr(ticket, "sla_status", None),
        "sla_remaining_minutes": getattr(ticket, "sla_remaining_minutes", None),
        "sla_first_response_due_at": getattr(ticket, "sla_first_response_due_at", None),
        "sla_resolution_due_at": getattr(ticket, "sla_resolution_due_at", None),
        "sla_first_response_breached": bool(getattr(ticket, "sla_first_response_breached", False)),
        "sla_resolution_breached": bool(getattr(ticket, "sla_resolution_breached", False)),
        "sla_last_synced_at": getattr(ticket, "sla_last_synced_at", None),
        "created_at": _normalize_datetime(getattr(ticket, "created_at", None)),
        "updated_at": _normalize_datetime(getattr(ticket, "updated_at", None)),
        "resolution": clean_multiline(getattr(ticket, "resolution", None)) or None,
        "change_risk": getattr(ticket, "change_risk", None),
        "change_scheduled_at": getattr(ticket, "change_scheduled_at", None),
        "change_approved": getattr(ticket, "change_approved", None),
        "change_approved_by": clean_single_line(getattr(ticket, "change_approved_by", None)) or None,
        "change_approved_at": getattr(ticket, "change_approved_at", None),
        "tags": _normalize_tags(getattr(ticket, "tags", []) or []),
        "comments": comments,
    }


def serialize_ticket_out(ticket: Any) -> tuple[TicketOut, bool]:
    try:
        return TicketOut.model_validate(ticket), False
    except ValidationError:
        payload = _sanitized_ticket_payload(ticket)
        return TicketOut.model_validate(payload), True
