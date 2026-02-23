"""SLA debug endpoints."""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Path, Query
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
from app.services.ai.ai_sla_risk import evaluate_sla_risk
from app.services.sla.auto_escalation import apply_escalation, compute_escalation
from app.services.tickets import get_ticket_for_user

router = APIRouter(dependencies=[Depends(rate_limit()), Depends(get_current_user)])
logger = logging.getLogger(__name__)

_DEFAULT_BATCH_LIMIT = 200
_DEFAULT_MAX_AGE_MINUTES = 10
_DEFAULT_STALE_STATUS_MINUTES = 120
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
            _record_automation_event(
                db,
                ticket_id=ticket.id,
                event_type="AUTO_ESCALATION",
                actor=f"user:{current_user.id}",
                before_snapshot=before_snapshot,
                after_snapshot=_snapshot(ticket),
                meta={"reason": ticket.priority_escalation_reason, "to_priority": _priority_value(ticket.priority)},
            )
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        raise BadRequestError("sla_sync_failed", details={"ticket_id": ticket_id, "error": str(exc)})

    db.refresh(ticket)
    return _snapshot(ticket)


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


@router.get("/ticket/{ticket_id}/ai-risk/latest")
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
    if latest is None:
        return {"ticket_id": ticket_id, "latest": None}

    return {
        "ticket_id": ticket_id,
        "risk_score": latest.risk_score,
        "confidence": latest.confidence,
        "suggested_priority": latest.suggested_priority,
        "reasoning_summary": latest.reasoning_summary,
        "model_version": latest.model_version,
        "decision_source": latest.decision_source,
        "created_at": _iso(latest.created_at),
    }


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
        stale_notified = 0
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
                result["dry_run_tickets"].append(
                    {
                        "ticket_id": ticket.id,
                        "jira_key": jira_key,
                        "would_sync": bool(sync_ok),
                        "would_escalate": bool(would_escalate),
                        "would_stale_notify": bool(would_stale_notify),
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
                    _record_automation_event(
                        db,
                        ticket_id=ticket.id,
                        event_type="AUTO_ESCALATION",
                        actor="system:n8n",
                        before_snapshot=before_snapshot,
                        after_snapshot=_snapshot(ticket),
                        meta={"reason": ticket.priority_escalation_reason, "to_priority": _priority_value(ticket.priority)},
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
                db.commit()
                risk_score = evaluation.get("risk_score")
                if risk_score is not None:
                    score_value = float(risk_score)
                    ai_evaluated += 1
                    ai_risk_total += score_value
                    if score_value >= 80:
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
