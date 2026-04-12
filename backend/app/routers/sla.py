"""SLA debug endpoints."""

from __future__ import annotations

import csv
import datetime as dt
import io
import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Path, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_user
from app.core.exceptions import BadRequestError, InsufficientPermissionsError, NotFoundError
from app.core.rate_limit import rate_limit
from app.db.session import get_db
from app.integrations.jira.sla_sync import sync_ticket_sla
from app.models.ai_sla_risk_evaluation import AiSlaRiskEvaluation
from app.models.automation_event import AutomationEvent
from app.models.notification import Notification
from app.models.enums import TicketStatus, UserRole
from app.models.ticket import Ticket
from app.models.user import User
from app.services.ai.ai_sla_risk import build_sla_advisory, evaluate_sla_risk
from app.services.ai.orchestrator import get_sla_advice
from app.services.notifications_service import (
    EVENT_AI_SLA_RISK_HIGH,
    EVENT_SLA_AT_RISK,
    EVENT_SLA_BREACHED,
    create_notifications_for_users,
    resolve_ticket_recipients,
)
from app.services.sla.auto_escalation import apply_escalation, compute_escalation
from app.services.tickets import get_ticket_for_user, select_best_assignee

router = APIRouter(dependencies=[Depends(rate_limit()), Depends(get_current_user)])
logger = logging.getLogger(__name__)

_DEFAULT_BATCH_LIMIT = 200
_DEFAULT_MAX_AGE_MINUTES = 10
_DEFAULT_STALE_STATUS_MINUTES = max(1, int(settings.SLA_STALE_STATUS_MINUTES))
_DEFAULT_DEADLINE_ALERT_MINUTES = max(1, int(settings.SLA_DEADLINE_ALERT_MINUTES))
_DEFAULT_AT_RISK_MINUTES = max(1, int(settings.SLA_AT_RISK_MINUTES))
_DEFAULT_AI_HIGH_RISK_THRESHOLD = max(0.0, min(float(settings.SLA_AI_HIGH_RISK_SCORE_THRESHOLD), 1.0))
_MAX_FAILURES = 20
_MAX_ESCALATIONS = 50
_ALLOWED_SLA_STATUSES = {"ok", "at_risk", "breached", "paused", "completed", "unknown"}
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
    stale_status_minutes: int = Field(default=_DEFAULT_STALE_STATUS_MINUTES, ge=1)
    dry_run: bool = False


class TicketSlaAdvisoryOut(BaseModel):
    ticket_id: str
    remaining_seconds: int
    is_breached: bool
    ai_risk_score: float
    rag_advice_text: str


class TicketAiSlaAdvisoryOut(BaseModel):
    ticket_id: str
    risk_score: float = Field(ge=0.0, le=1.0)
    band: str
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    advisory_mode: str
    evaluated_at: str
    remaining_seconds: int = 0
    suggested_priority: str | None = None
    sla_elapsed_ratio: float = Field(default=0.0, ge=0.0, le=1.0)
    time_consumed_percent: int = Field(default=0, ge=0, le=100)
    model_version: str = "deterministic-sla-v1"
    decision_source: str = "deterministic"
    created_at: str


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


def _risk_score_as_unit(value: Any) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.0
    if score <= 1.0:
        return max(0.0, min(score, 1.0))
    return max(0.0, min(score / 100.0, 1.0))


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
        "priority": _priority_value(ticket.priority),
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


def _is_breached_ticket(ticket: Ticket) -> bool:
    return bool(ticket.sla_first_response_breached or ticket.sla_resolution_breached)


def _remaining_seconds(ticket: Ticket) -> int:
    value = getattr(ticket, "sla_remaining_minutes", None)
    if value is None:
        return 0
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, minutes * 60)


def _status_change_stale(ticket: Ticket, *, stale_before: dt.datetime) -> bool:
    updated_at = _as_utc(ticket.updated_at)
    stale_cutoff = _as_utc(stale_before)
    if updated_at is None or stale_cutoff is None:
        return False
    if _status_value(ticket.status) in {TicketStatus.resolved.value, TicketStatus.closed.value}:
        return False
    return updated_at <= stale_cutoff


def _resolve_notification_recipients(db: Session, ticket: Ticket) -> list[User]:
    recipients_by_id: dict[str, User] = {}

    admins = db.execute(select(User).where(User.role == UserRole.admin)).scalars().all()
    for admin in admins:
        recipients_by_id[str(admin.id)] = admin

    assignee_value = str(ticket.assignee or "").strip().lower()
    if assignee_value:
        assignee_user = db.execute(
            select(User).where((User.email.ilike(assignee_value)) | (User.name.ilike(assignee_value)))
        ).scalars().first()
        if assignee_user:
            recipients_by_id[str(assignee_user.id)] = assignee_user

    return list(recipients_by_id.values())


def _stale_notification_exists_recently(db: Session, *, user_id: UUID, link: str, cooldown_since: dt.datetime) -> bool:
    existing = db.execute(
        select(Notification.id).where(
            Notification.user_id == user_id,
            Notification.link == link,
            Notification.source == "sla",
            Notification.read_at.is_(None),
            Notification.created_at >= cooldown_since,
        )
    ).scalars().first()
    return existing is not None


def _create_stale_status_notifications(
    db: Session,
    *,
    ticket: Ticket,
    stale_status_minutes: int,
    cooldown_minutes: int = 120,
) -> int:
    link = f"/tickets/{ticket.id}"
    recipients = _resolve_notification_recipients(db, ticket)
    if not recipients:
        return 0

    now = dt.datetime.now(dt.timezone.utc)
    stale_hours = round(stale_status_minutes / 60, 1)
    title = f"Stale ticket status: {ticket.id}"
    body = (
        f"Ticket '{ticket.title}' has not changed status for ~{stale_hours}h. "
        f"Current status: {_status_value(ticket.status) or 'unknown'}."
    )
    severity = "warning"
    created = 0
    cooldown_since = now - dt.timedelta(minutes=cooldown_minutes)

    for user in recipients:
        if _stale_notification_exists_recently(db, user_id=user.id, link=link, cooldown_since=cooldown_since):
            continue
        db.add(
            Notification(
                user_id=user.id,
                title=title,
                body=body,
                severity=severity,
                link=link,
                source="sla",
            )
        )
        created += 1

    return created


def _create_escalation_notifications(db: Session, *, ticket: Ticket) -> int:
    recipients = resolve_ticket_recipients(db, ticket=ticket, include_admins=True)
    created = create_notifications_for_users(
        db,
        users=recipients,
        title=f"SLA auto-escalation: {ticket.id}",
        body=f"Priority escalated to {_priority_value(ticket.priority)} ({ticket.priority_escalation_reason or 'sla_policy'}).",
        severity="high",
        link=f"/tickets/{ticket.id}",
        source="sla",
        cooldown_minutes=30,
        metadata_json={
            "ticket_id": ticket.id,
            "ticket_title": ticket.title,
            "reason": ticket.priority_escalation_reason or "sla_policy",
            "band": str(getattr(ticket, "sla_status", None) or "at_risk"),
        },
        action_type="escalate",
        action_payload={"ticket_id": ticket.id},
        event_type=EVENT_SLA_AT_RISK,
    )
    return len(created)


def _deadline_alert_state(ticket: Ticket, *, threshold_minutes: int) -> tuple[bool, str, int | None]:
    sla_status = str(getattr(ticket, "sla_status", None) or "unknown").strip().lower()
    remaining = getattr(ticket, "sla_remaining_minutes", None)
    if sla_status == "breached":
        return True, "breached", remaining
    if sla_status != "at_risk":
        return False, sla_status, remaining
    if remaining is None:
        return True, "at_risk", remaining
    try:
        remaining_value = int(remaining)
    except (TypeError, ValueError):
        return True, "at_risk", None
    return remaining_value <= max(1, threshold_minutes), "at_risk", remaining_value


def _create_deadline_alert_notifications(
    db: Session,
    *,
    ticket: Ticket,
    threshold_minutes: int = _DEFAULT_DEADLINE_ALERT_MINUTES,
    cooldown_minutes: int = 30,
) -> int:
    should_alert, status, remaining = _deadline_alert_state(ticket, threshold_minutes=threshold_minutes)
    if not should_alert:
        return 0

    recipients = resolve_ticket_recipients(db, ticket=ticket, include_admins=True)
    if not recipients:
        return 0

    is_breached = status == "breached"
    severity = "critical" if is_breached else "warning"
    title = f"SLA breached: {ticket.id}" if is_breached else f"SLA deadline approaching: {ticket.id}"
    remaining_text = (
        "Remaining time unavailable"
        if remaining is None
        else ("Deadline already passed" if remaining <= 0 else f"{remaining} minute(s) remaining")
    )
    body = (
        f"Ticket '{ticket.title}' is currently {status}. {remaining_text}. "
        f"Current priority: {_priority_value(ticket.priority) or 'unknown'}."
    )
    created = create_notifications_for_users(
        db,
        users=recipients,
        title=title,
        body=body,
        severity=severity,
        link=f"/tickets/{ticket.id}",
        source="sla",
        cooldown_minutes=cooldown_minutes,
        metadata_json={
            "ticket_id": ticket.id,
            "ticket_title": ticket.title,
            "band": status,
            "remaining_minutes": remaining,
            "is_breached": is_breached,
        },
        action_type="view",
        action_payload={"ticket_id": ticket.id},
        event_type=EVENT_SLA_BREACHED if is_breached else EVENT_SLA_AT_RISK,
    )
    return len(created)


def _create_high_risk_sla_notifications(
    db: Session,
    *,
    ticket: Ticket,
    unit_risk_score: float,
    suggested_priority: str | None,
    threshold: float,
    cooldown_minutes: int = 30,
) -> int:
    if unit_risk_score <= threshold:
        return 0
    if str(getattr(ticket, "sla_status", None) or "").strip().lower() != "at_risk":
        return 0

    recipients = resolve_ticket_recipients(db, ticket=ticket, include_admins=True)
    if not recipients:
        return 0

    suggested_assignee = select_best_assignee(db, category=ticket.category, priority=ticket.priority)
    title = f"High-risk SLA ticket: {ticket.id}"
    body = (
        f"AI advisory risk score is {round(unit_risk_score, 2)} (threshold {round(threshold, 2)}). "
        f"Status is at_risk with {ticket.sla_remaining_minutes if ticket.sla_remaining_minutes is not None else 'unknown'} minute(s) remaining. "
        f"Suggested priority: {suggested_priority or _priority_value(ticket.priority)}."
    )
    created = create_notifications_for_users(
        db,
        users=recipients,
        title=title,
        body=body,
        severity="high",
        link=f"/tickets/{ticket.id}",
        source="sla",
        cooldown_minutes=cooldown_minutes,
        metadata_json={
            "ticket_id": ticket.id,
            "ticket_title": ticket.title,
            "risk_score": round(unit_risk_score, 3),
            "suggested_priority": suggested_priority or _priority_value(ticket.priority),
            "band": "high",
            "remaining_minutes": ticket.sla_remaining_minutes,
        },
        action_type="reassign",
        action_payload={
            "ticket_id": ticket.id,
            "assignee": suggested_assignee,
            "reason": "ai_sla_high_risk",
            "risk_score": round(unit_risk_score, 3),
        },
        event_type=EVENT_AI_SLA_RISK_HIGH,
    )
    return len(created)


def _resolve_ai_sla_mode() -> str:
    mode = str(settings.AI_SLA_RISK_MODE or "shadow").strip().lower()
    return mode if mode in {"shadow", "assist"} else "shadow"


def _resolve_assignee_role(db: Session, ticket: Ticket) -> str | None:
    assignee_value = str(ticket.assignee or "").strip().lower()
    if not assignee_value:
        return None
    assignee_user = db.execute(
        select(User).where((User.email.ilike(assignee_value)) | (User.name.ilike(assignee_value)))
    ).scalars().first()
    if not assignee_user:
        return None
    specializations = [str(item).strip() for item in (assignee_user.specializations or []) if str(item).strip()]
    return ", ".join(specializations) if specializations else None


def _count_similar_incidents(db: Session, ticket: Ticket) -> int | None:
    if ticket.category is None:
        return None
    return int(
        db.execute(
            select(func.count(Ticket.id)).where(
                Ticket.id != ticket.id,
                Ticket.category == ticket.category,
                Ticket.status.in_(
                    [
                        TicketStatus.open,
                        TicketStatus.in_progress,
                        TicketStatus.pending,
                        TicketStatus.waiting_for_customer,
                        TicketStatus.waiting_for_support_vendor,
                    ]
                ),
            )
        ).scalar()
        or 0
    )


def _count_assignee_active_tickets(db: Session, ticket: Ticket) -> int | None:
    assignee_value = str(ticket.assignee or "").strip()
    if not assignee_value:
        return None
    return int(
        db.execute(
            select(func.count(Ticket.id)).where(
                Ticket.id != ticket.id,
                Ticket.assignee.ilike(assignee_value),
                Ticket.status.in_(
                    [
                        TicketStatus.open,
                        TicketStatus.in_progress,
                        TicketStatus.pending,
                        TicketStatus.waiting_for_customer,
                        TicketStatus.waiting_for_support_vendor,
                    ]
                ),
            )
        ).scalar()
        or 0
    )


def _latest_ai_evaluation_payload(latest: AiSlaRiskEvaluation | None) -> dict[str, Any] | None:
    if latest is None:
        return None
    return {
        "risk_score": latest.risk_score,
        "confidence": latest.confidence,
        "suggested_priority": latest.suggested_priority,
        "reasoning_summary": latest.reasoning_summary,
        "model_version": latest.model_version,
        "decision_source": latest.decision_source,
        "created_at": _iso(latest.created_at),
    }


def _build_ticket_sla_operational_advisory(
    db: Session,
    *,
    ticket: Ticket,
    latest: AiSlaRiskEvaluation | None = None,
) -> dict[str, Any]:
    similar_incidents = _count_similar_incidents(db, ticket)
    assignee_load = _count_assignee_active_tickets(db, ticket)
    advisory = build_sla_advisory(
        ticket,
        similar_incidents=similar_incidents,
        assignee_load=assignee_load,
        ai_evaluation=_latest_ai_evaluation_payload(latest),
    )
    evaluated_at = str(advisory.get("evaluated_at") or _iso(getattr(latest, "created_at", None)) or dt.datetime.now(dt.timezone.utc).isoformat())
    return {
        "ticket_id": ticket.id,
        "risk_score": float(advisory.get("risk_score") or 0.0),
        "band": str(advisory.get("band") or "low"),
        "confidence": float(advisory.get("confidence") or 0.0),
        "reasoning": [str(item).strip() for item in list(advisory.get("reasoning") or []) if str(item).strip()],
        "recommended_actions": [str(item).strip() for item in list(advisory.get("recommended_actions") or []) if str(item).strip()],
        "advisory_mode": str(advisory.get("advisory_mode") or "deterministic"),
        "evaluated_at": evaluated_at,
        "remaining_seconds": _remaining_seconds(ticket),
        "suggested_priority": advisory.get("suggested_priority"),
        "sla_elapsed_ratio": float(advisory.get("sla_elapsed_ratio") or 0.0),
        "time_consumed_percent": int(advisory.get("time_consumed_percent") or 0),
        "model_version": str(getattr(latest, "model_version", None) or "deterministic-sla-v1"),
        "decision_source": str(getattr(latest, "decision_source", None) or advisory.get("advisory_mode") or "deterministic"),
        "created_at": evaluated_at,
    }


def _persist_ai_risk_evaluation(
    db: Session,
    *,
    ticket: Ticket,
    evaluation: dict[str, Any],
    decision_source: str,
) -> None:
    db.add(
        AiSlaRiskEvaluation(
            ticket_id=ticket.id,
            risk_score=evaluation.get("risk_score"),
            confidence=evaluation.get("confidence"),
            suggested_priority=evaluation.get("suggested_priority"),
            reasoning_summary=str(evaluation.get("reasoning_summary") or "").strip() or "No reasoning returned.",
            model_version=str(evaluation.get("model_version") or settings.OLLAMA_MODEL),
            decision_source=decision_source,
        )
    )


def _build_ai_risk_summary(*, evaluated: int, risk_total: float, high_risk_detected: int, mode: str) -> dict[str, Any]:
    avg_risk_score = round(risk_total / evaluated, 2) if evaluated else 0.0
    return {
        "evaluated": evaluated,
        "avg_risk_score": avg_risk_score,
        "high_risk_detected": high_risk_detected,
        "shadow_mode": mode == "shadow",
    }


def _record_automation_event(
    db: Session,
    *,
    ticket_id: str,
    event_type: str,
    actor: str,
    before_snapshot: dict[str, Any] | None = None,
    after_snapshot: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    db.add(
        AutomationEvent(
            ticket_id=ticket_id,
            event_type=event_type,
            actor=actor,
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
            meta=meta,
        )
    )


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
        before_snapshot = _snapshot(ticket)
        sync_ticket_sla(db, ticket, ticket.jira_key)
        _record_automation_event(
            db,
            ticket_id=ticket.id,
            event_type="SLA_SYNC",
            actor=f"user:{current_user.id}",
            before_snapshot=before_snapshot,
            after_snapshot=_snapshot(ticket),
        )
        escalated = apply_escalation(db, ticket, actor=f"user:{current_user.id}")
        if escalated:
            notified = _create_escalation_notifications(db, ticket=ticket)
            _record_automation_event(
                db,
                ticket_id=ticket.id,
                event_type="AUTO_ESCALATION",
                actor=f"user:{current_user.id}",
                before_snapshot=before_snapshot,
                after_snapshot=_snapshot(ticket),
                meta={
                    "reason": ticket.priority_escalation_reason,
                    "to_priority": _priority_value(ticket.priority),
                    "notified": notified,
                },
            )
        deadline_alerted = _create_deadline_alert_notifications(db, ticket=ticket)
        if deadline_alerted > 0:
            _record_automation_event(
                db,
                ticket_id=ticket.id,
                event_type="SLA_DEADLINE_ALERT",
                actor=f"user:{current_user.id}",
                before_snapshot=before_snapshot,
                after_snapshot=_snapshot(ticket),
                meta={
                    "created": deadline_alerted,
                    "sla_status": str(ticket.sla_status or "unknown"),
                    "remaining_minutes": ticket.sla_remaining_minutes,
                },
            )
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        raise BadRequestError("sla_sync_failed", details={"ticket_id": ticket_id, "error": str(exc)})

    db.refresh(ticket)
    return _snapshot(ticket)


@router.get("/ticket/{ticket_id}/advisory", response_model=TicketSlaAdvisoryOut)
def get_ticket_sla_advisory(
    ticket_id: str = Path(..., min_length=3, max_length=32),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TicketSlaAdvisoryOut:
    ticket = get_ticket_for_user(db, ticket_id, current_user)
    if not ticket:
        raise NotFoundError("ticket_not_found", details={"ticket_id": ticket_id})

    latest = db.execute(
        select(AiSlaRiskEvaluation)
        .where(AiSlaRiskEvaluation.ticket_id == ticket_id)
        .order_by(AiSlaRiskEvaluation.created_at.desc())
        .limit(1)
    ).scalars().first()
    advisory_payload = _build_ticket_sla_operational_advisory(db, ticket=ticket, latest=latest)

    advisory = get_sla_advice(db, ticket=ticket)
    return TicketSlaAdvisoryOut(
        ticket_id=ticket.id,
        remaining_seconds=_remaining_seconds(ticket),
        is_breached=_is_breached_ticket(ticket),
        ai_risk_score=round(float(advisory_payload.get("risk_score") or 0.0), 3),
        rag_advice_text=str(advisory.get("advice_text") or "").strip() or "No advisory available.",
    )


@router.get("/metrics")
def get_sla_metrics(
    status: str | None = Query(default=None, description="Optional ticket status filter"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    if current_user.role not in {UserRole.admin, UserRole.agent}:
        raise InsufficientPermissionsError("forbidden")

    base_query = select(Ticket).where(
        Ticket.jira_key.is_not(None),
        Ticket.jira_key != "",
    )
    if status:
        normalized_status = _normalize_status_token(status)
        status_enum = _STATUS_ALIASES.get(normalized_status)
        if status_enum is None:
            raise BadRequestError("invalid_status_filter", details={"status": status})
        base_query = base_query.where(Ticket.status == status_enum)

    tickets = db.execute(base_query).scalars().all()
    if not tickets:
        return {
            "total_tickets": 0,
            "sla_breakdown": {},
            "breach_rate": 0.0,
            "at_risk_rate": 0.0,
            "avg_remaining_minutes": None,
        }

    sla_counts = {name: 0 for name in _ALLOWED_SLA_STATUSES}
    total_remaining = 0
    remaining_count = 0

    for ticket in tickets:
        current_sla_status = str(ticket.sla_status or "unknown").strip().lower()
        if current_sla_status in _ALLOWED_SLA_STATUSES:
            sla_counts[current_sla_status] += 1
        else:
            sla_counts["unknown"] += 1

        if ticket.sla_remaining_minutes is not None and ticket.sla_remaining_minutes >= 0:
            total_remaining += int(ticket.sla_remaining_minutes)
            remaining_count += 1

    total = len(tickets)
    breach_rate = round((sla_counts["breached"] / total) * 100, 1) if total else 0.0
    at_risk_rate = round((sla_counts["at_risk"] / total) * 100, 1) if total else 0.0
    avg_remaining = round(total_remaining / remaining_count, 1) if remaining_count else None

    return {
        "total_tickets": total,
        "sla_breakdown": sla_counts,
        "breach_rate": breach_rate,
        "at_risk_rate": at_risk_rate,
        "avg_remaining_minutes": avg_remaining,
    }


_CSV_COLUMNS = [
    "ticket_id", "jira_key", "title", "status", "priority", "category", "assignee",
    "sla_status", "sla_remaining_minutes", "sla_elapsed_minutes",
    "sla_first_response_due_at", "sla_resolution_due_at",
    "sla_first_response_breached", "sla_resolution_breached",
]


@router.get("/export")
def export_sla_csv(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    if current_user.role not in {UserRole.admin, UserRole.agent}:
        raise InsufficientPermissionsError("forbidden")

    # ISO 27001 A.12 — log bulk data exports
    from app.models.security_event import DATA_EXPORT
    from app.services.auth import log_security_event
    log_security_event(
        db, DATA_EXPORT,
        user_id=current_user.id,
        metadata={"export_type": "sla_csv", "scope": "all_tickets"},
    )

    tickets = db.execute(select(Ticket)).scalars().all()

    def _fmt(v: Any) -> str:
        if v is None:
            return ""
        if isinstance(v, dt.datetime):
            return v.isoformat()
        return str(v)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(_CSV_COLUMNS)
    for t in tickets:
        writer.writerow([
            _fmt(t.id),
            _fmt(t.jira_key),
            _fmt(t.title),
            _fmt(t.status.value if hasattr(t.status, "value") else t.status),
            _fmt(t.priority.value if hasattr(t.priority, "value") else t.priority),
            _fmt(t.category),
            _fmt(t.assignee),
            _fmt(t.sla_status),
            _fmt(t.sla_remaining_minutes),
            _fmt(t.sla_elapsed_minutes),
            _fmt(t.sla_first_response_due_at),
            _fmt(t.sla_resolution_due_at),
            _fmt(t.sla_first_response_breached),
            _fmt(t.sla_resolution_breached),
        ])

    filename = f"sla_export_{dt.date.today().isoformat()}.csv"
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/ticket/{ticket_id}/ai-risk/latest", response_model=TicketAiSlaAdvisoryOut)
def get_ticket_ai_risk_latest(
    ticket_id: str = Path(..., min_length=3, max_length=32),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    ticket = get_ticket_for_user(db, ticket_id, current_user)
    if not ticket:
        raise NotFoundError("ticket_not_found", details={"ticket_id": ticket_id})

    latest = db.execute(
        select(AiSlaRiskEvaluation)
        .where(AiSlaRiskEvaluation.ticket_id == ticket_id)
        .order_by(AiSlaRiskEvaluation.created_at.desc())
        .limit(1)
    ).scalars().first()
    return _build_ticket_sla_operational_advisory(db, ticket=ticket, latest=latest)


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
    stale_status_before = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=params.stale_status_minutes)

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
        "stale_notified": 0,
        "deadline_alerted": 0,
        "skipped": 0,
        "failed": 0,
        "failures": [],
        "escalations": [],
        "dry_run": bool(params.dry_run),
        "proposed_actions": [],
        "dry_run_tickets": [],
    }
    ai_mode = _resolve_ai_sla_mode()
    ai_enabled = bool(settings.AI_SLA_RISK_ENABLED)
    ai_evaluated = 0
    ai_risk_total = 0.0
    ai_high_risk_detected = 0

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
        would_escalate = False
        would_stale_notify = False
        would_deadline_alert = False
        stale_notified = 0
        deadline_alerted = 0
        stale_recipients_count = 0
        escalation_data: dict[str, str] | None = None
        processing_error: str | None = None

        if params.dry_run:
            try:
                savepoint = db.begin_nested()
                sync_result = sync_ticket_sla(db, ticket, jira_key)
                sync_ok = _sync_succeeded(before=before_synced_at, after=ticket.sla_last_synced_at, sync_result=sync_result)
                target_priority, reason = compute_escalation(ticket)
                if target_priority is not None:
                    would_escalate = True
                    result["proposed_actions"].append(
                        {
                            "ticket_id": ticket.id,
                            "jira_key": jira_key,
                            "action_type": "ESCALATE_PRIORITY",
                            "details": {
                                "from_priority": from_priority,
                                "to_priority": _priority_value(target_priority),
                                "reason": reason,
                            },
                        }
                    )
                if sync_ok:
                    result["proposed_actions"].append(
                        {
                            "ticket_id": ticket.id,
                            "jira_key": jira_key,
                            "action_type": "SYNC_SLA",
                            "details": {},
                        }
                    )
                    if str(getattr(ticket, "sla_status", None) or "unknown").strip().lower() == "at_risk":
                        result["proposed_actions"].append(
                            {
                                "ticket_id": ticket.id,
                                "jira_key": jira_key,
                                "action_type": "SLA_AT_RISK",
                                "details": {
                                    "remaining_minutes": ticket.sla_remaining_minutes,
                                },
                            }
                        )

                if _status_change_stale(ticket, stale_before=stale_status_before):
                    stale_recipients_count = len(_resolve_notification_recipients(db, ticket))
                    if stale_recipients_count > 0:
                        would_stale_notify = True
                        result["proposed_actions"].append(
                            {
                                "ticket_id": ticket.id,
                                "jira_key": jira_key,
                                "action_type": "STALE_NOTIFY",
                                "details": {
                                    "recipients_count": stale_recipients_count,
                                    "stale_minutes": params.stale_status_minutes,
                                },
                            }
                        )
                should_deadline_alert, deadline_status, deadline_remaining = _deadline_alert_state(
                    ticket,
                    threshold_minutes=_DEFAULT_DEADLINE_ALERT_MINUTES,
                )
                if should_deadline_alert:
                    deadline_recipients_count = len(resolve_ticket_recipients(db, ticket=ticket, include_admins=True))
                    if deadline_recipients_count > 0:
                        would_deadline_alert = True
                        result["proposed_actions"].append(
                            {
                                "ticket_id": ticket.id,
                                "jira_key": jira_key,
                                "action_type": "SLA_DEADLINE_ALERT",
                                "details": {
                                    "sla_status": deadline_status,
                                    "remaining_minutes": deadline_remaining,
                                    "recipients_count": deadline_recipients_count,
                                },
                            }
                        )
                result["dry_run_tickets"].append(
                    {
                        "ticket_id": ticket.id,
                        "jira_key": jira_key,
                        "would_sync": bool(sync_ok),
                        "would_escalate": bool(would_escalate),
                        "would_stale_notify": bool(would_stale_notify),
                        "would_deadline_alert": bool(would_deadline_alert),
                    }
                )
                savepoint.rollback()
                db.refresh(ticket)
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                processing_error = str(exc)
        else:
            try:
                before_snapshot = _snapshot(ticket)
                sync_result = sync_ticket_sla(db, ticket, jira_key)
                sync_ok = _sync_succeeded(before=before_synced_at, after=ticket.sla_last_synced_at, sync_result=sync_result)
                if sync_ok:
                    _record_automation_event(
                        db,
                        ticket_id=ticket.id,
                        event_type="SLA_SYNC",
                        actor="system:n8n",
                        before_snapshot=before_snapshot,
                        after_snapshot=_snapshot(ticket),
                    )

                escalated_now = apply_escalation(db, ticket, actor="system:n8n")
                if escalated_now:
                    escalation_data = _serialize_escalation(ticket, from_priority=from_priority)
                    escalation_notified = _create_escalation_notifications(db, ticket=ticket)
                    _record_automation_event(
                        db,
                        ticket_id=ticket.id,
                        event_type="AUTO_ESCALATION",
                        actor="system:n8n",
                        before_snapshot=before_snapshot,
                        after_snapshot=_snapshot(ticket),
                        meta={
                            "reason": ticket.priority_escalation_reason,
                            "to_priority": _priority_value(ticket.priority),
                            "notified": escalation_notified,
                        },
                    )
                if _status_change_stale(ticket, stale_before=stale_status_before):
                    stale_notified = _create_stale_status_notifications(
                        db,
                        ticket=ticket,
                        stale_status_minutes=params.stale_status_minutes,
                    )
                    if stale_notified > 0:
                        _record_automation_event(
                            db,
                            ticket_id=ticket.id,
                            event_type="STALE_NOTIFY",
                            actor="system:n8n",
                            before_snapshot=before_snapshot,
                            after_snapshot=_snapshot(ticket),
                            meta={"created": stale_notified},
                        )
                deadline_alerted = _create_deadline_alert_notifications(db, ticket=ticket)
                if deadline_alerted > 0:
                    _record_automation_event(
                        db,
                        ticket_id=ticket.id,
                        event_type="SLA_DEADLINE_ALERT",
                        actor="system:n8n",
                        before_snapshot=before_snapshot,
                        after_snapshot=_snapshot(ticket),
                        meta={
                            "created": deadline_alerted,
                            "sla_status": str(ticket.sla_status or "unknown"),
                            "remaining_minutes": ticket.sla_remaining_minutes,
                        },
                    )
                db.commit()
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                processing_error = str(exc)

        if processing_error is not None:
            if not params.dry_run:
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
        elif not params.dry_run:
            result["failed"] += 1
            if len(result["failures"]) < _MAX_FAILURES:
                result["failures"].append(
                    {
                        "ticket_id": ticket.id,
                        "jira_key": jira_key,
                        "error": "sla_sync_failed",
                    }
                )

        if escalated_now or would_escalate:
            result["escalated"] += 1
            if escalation_data is not None and len(result["escalations"]) < _MAX_ESCALATIONS:
                result["escalations"].append(escalation_data)
        if stale_notified or would_stale_notify:
            result["stale_notified"] += stale_notified
        if deadline_alerted or would_deadline_alert:
            result["deadline_alerted"] += deadline_alerted

        if ai_enabled and not params.dry_run:
            try:
                assignee_role = _resolve_assignee_role(db, ticket)
                similar_incidents = _count_similar_incidents(db, ticket)
                evaluation = evaluate_sla_risk(
                    ticket,
                    assignee_role=assignee_role,
                    similar_incidents=similar_incidents,
                )
                _persist_ai_risk_evaluation(
                    db,
                    ticket=ticket,
                    evaluation=evaluation,
                    decision_source=ai_mode,
                )
                _record_automation_event(
                    db,
                    ticket_id=ticket.id,
                    event_type="AI_RISK_EVALUATION",
                    actor="system:n8n",
                    before_snapshot=None,
                    after_snapshot=None,
                    meta={
                        "risk_score": evaluation.get("risk_score"),
                        "confidence": evaluation.get("confidence"),
                        "model_version": evaluation.get("model_version"),
                        "decision_source": ai_mode,
                    },
                )
                unit_score = _risk_score_as_unit(evaluation.get("risk_score"))
                current_sla_status = str(getattr(ticket, "sla_status", None) or "").strip().lower()
                if unit_score > _DEFAULT_AI_HIGH_RISK_THRESHOLD and current_sla_status == "at_risk":
                    high_risk_notified = _create_high_risk_sla_notifications(
                        db,
                        ticket=ticket,
                        unit_risk_score=unit_score,
                        suggested_priority=str(evaluation.get("suggested_priority") or "").strip() or None,
                        threshold=_DEFAULT_AI_HIGH_RISK_THRESHOLD,
                    )
                    _record_automation_event(
                        db,
                        ticket_id=ticket.id,
                        event_type="AUTO_ESCALATION",
                        actor="system:ai_sla_advisor",
                        before_snapshot=_snapshot(ticket),
                        after_snapshot=_snapshot(ticket),
                        meta={
                            "trigger": "ai_risk_threshold",
                            "unit_risk_score": round(unit_score, 3),
                            "threshold": _DEFAULT_AI_HIGH_RISK_THRESHOLD,
                            "sla_status": current_sla_status or "unknown",
                            "notified": high_risk_notified,
                        },
                    )
                db.commit()
                risk_score = evaluation.get("risk_score")
                if risk_score is not None:
                    score_value = _risk_score_as_unit(risk_score)
                    ai_evaluated += 1
                    ai_risk_total += score_value
                    if score_value >= _DEFAULT_AI_HIGH_RISK_THRESHOLD:
                        ai_high_risk_detected += 1
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                logger.warning("AI SLA risk persistence failed for ticket %s: %s", ticket.id, exc)

    if params.dry_run:
        result["failed"] = 0

    result["ai_risk_summary"] = _build_ai_risk_summary(
        evaluated=ai_evaluated,
        risk_total=ai_risk_total,
        high_risk_detected=ai_high_risk_detected,
        mode=ai_mode,
    )
    return result
