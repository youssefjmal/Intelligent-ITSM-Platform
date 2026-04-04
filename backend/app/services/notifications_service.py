"""Service helpers for notifications CRUD, routing, targeting, and read-state updates."""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
import re
from datetime import time as dtime
from typing import Any, Iterable
from uuid import UUID

import httpx

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.notification_delivery_event import NotificationDeliveryEvent
from app.models.notification_preference import NotificationPreference
from app.models.notification import Notification
from app.models.problem import Problem
from app.models.ticket import Ticket
from app.models.enums import UserRole
from app.models.user import User
from app.services.email_dispatcher import deliver_notification_email

logger = logging.getLogger(__name__)

EVENT_TICKET_CREATED = "ticket_created"
EVENT_TICKET_ASSIGNED = "ticket_assigned"
EVENT_TICKET_REASSIGNED = "ticket_reassigned"
EVENT_TICKET_COMMENTED = "ticket_commented"
EVENT_TICKET_STATUS_CHANGED = "ticket_status_changed"
EVENT_TICKET_RESOLVED = "ticket_resolved"
EVENT_SLA_AT_RISK = "sla_at_risk"
EVENT_SLA_BREACHED = "sla_breached"
EVENT_SLA_RECOVERED = "sla_recovered"
EVENT_PROBLEM_CREATED = "problem_created"
EVENT_PROBLEM_LINKED = "problem_linked"
EVENT_AI_RECOMMENDATION_READY = "ai_recommendation_ready"
EVENT_AI_SLA_RISK_HIGH = "ai_sla_risk_high"
EVENT_MENTION = "mention"
EVENT_SYSTEM_ALERT = "system_alert"

ROUTE_IN_APP_ONLY = "in_app_only"
ROUTE_DIRECT_EMAIL = "direct_email"
ROUTE_DIGEST_QUEUE = "digest_queue"
ROUTE_N8N_WORKFLOW = "n8n_workflow"


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


_VALID_EVENT_TYPES = {
    EVENT_TICKET_CREATED,
    EVENT_TICKET_ASSIGNED,
    EVENT_TICKET_REASSIGNED,
    EVENT_TICKET_COMMENTED,
    EVENT_TICKET_STATUS_CHANGED,
    EVENT_TICKET_RESOLVED,
    EVENT_SLA_AT_RISK,
    EVENT_SLA_BREACHED,
    EVENT_SLA_RECOVERED,
    EVENT_PROBLEM_CREATED,
    EVENT_PROBLEM_LINKED,
    EVENT_AI_RECOMMENDATION_READY,
    EVENT_AI_SLA_RISK_HIGH,
    EVENT_MENTION,
    EVENT_SYSTEM_ALERT,
}
_SEVERITY_RANK = {"low": 1, "info": 2, "medium": 2, "warning": 3, "high": 4, "critical": 5}
_PINNED_EVENT_TYPES = {EVENT_SLA_BREACHED, EVENT_PROBLEM_CREATED, EVENT_SYSTEM_ALERT}
_EVENT_PREF_FIELDS = {
    EVENT_TICKET_ASSIGNED: "ticket_assignment_enabled",
    EVENT_TICKET_REASSIGNED: "ticket_assignment_enabled",
    EVENT_TICKET_COMMENTED: "ticket_comment_enabled",
    EVENT_TICKET_STATUS_CHANGED: "ticket_comment_enabled",
    EVENT_TICKET_RESOLVED: "ticket_comment_enabled",
    EVENT_MENTION: "ticket_comment_enabled",
    EVENT_SLA_AT_RISK: "sla_notifications_enabled",
    EVENT_SLA_BREACHED: "sla_notifications_enabled",
    EVENT_SLA_RECOVERED: "sla_notifications_enabled",
    EVENT_AI_SLA_RISK_HIGH: "sla_notifications_enabled",
    EVENT_PROBLEM_CREATED: "problem_notifications_enabled",
    EVENT_PROBLEM_LINKED: "problem_notifications_enabled",
    EVENT_AI_RECOMMENDATION_READY: "ai_notifications_enabled",
}
_N8N_WORKFLOW_BY_EVENT = {
    EVENT_SLA_BREACHED: "sla-breach-alerting",
    EVENT_PROBLEM_CREATED: "problem-detected",
    EVENT_SYSTEM_ALERT: "critical-ticket-detected",
}
_DIGEST_FRIENDLY_EVENTS = {
    EVENT_TICKET_ASSIGNED,
    EVENT_TICKET_REASSIGNED,
    EVENT_TICKET_COMMENTED,
    EVENT_TICKET_STATUS_CHANGED,
    EVENT_SLA_AT_RISK,
    EVENT_AI_RECOMMENDATION_READY,
    EVENT_AI_SLA_RISK_HIGH,
    EVENT_PROBLEM_LINKED,
}
_IMMEDIATE_EMAIL_EVENTS = {
    EVENT_MENTION,
    EVENT_TICKET_RESOLVED,
    EVENT_SLA_BREACHED,
    EVENT_PROBLEM_CREATED,
    EVENT_SYSTEM_ALERT,
}
_EVENT_DEFAULT_COOLDOWNS = {
    EVENT_TICKET_ASSIGNED: 20,
    EVENT_TICKET_REASSIGNED: 20,
    EVENT_TICKET_COMMENTED: 10,
    EVENT_MENTION: 5,
    EVENT_TICKET_STATUS_CHANGED: 20,
    EVENT_TICKET_RESOLVED: 60,
    EVENT_SLA_AT_RISK: 45,
    EVENT_SLA_BREACHED: 30,
    EVENT_SLA_RECOVERED: 60,
    EVENT_PROBLEM_CREATED: 30,
    EVENT_PROBLEM_LINKED: 60,
    EVENT_AI_RECOMMENDATION_READY: 180,
    EVENT_AI_SLA_RISK_HIGH: 60,
    EVENT_SYSTEM_ALERT: 20,
}
_MENTION_PATTERN = re.compile(r"(?<!\w)@([A-Za-z0-9._-]+(?:@[A-Za-z0-9._-]+\.[A-Za-z]{2,})?)")


def _severity_ge(left: str, right: str) -> bool:
    return _SEVERITY_RANK.get(str(left or "").lower(), 0) >= _SEVERITY_RANK.get(str(right or "").lower(), 0)


def _parse_time(value: str | None) -> dtime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        hh, mm = text.split(":")
        return dtime(hour=int(hh), minute=int(mm))
    except Exception:
        return None


def _format_time(value: dtime | None) -> str | None:
    if value is None:
        return None
    return f"{value.hour:02d}:{value.minute:02d}"


def _is_now_in_quiet_hours(now: dt.datetime, start: dtime | None, end: dtime | None) -> bool:
    if start is None or end is None:
        return False
    current = now.timetz().replace(tzinfo=None)
    if start < end:
        return start <= current < end
    return current >= start or current < end


def _normalize_event_type(event_type: str | None, *, source: str | None = None) -> str:
    normalized = str(event_type or "").strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in _VALID_EVENT_TYPES:
        return normalized
    source_value = str(source or "").strip().lower()
    if source_value == "sla":
        return EVENT_SLA_AT_RISK
    if source_value == "problem":
        return EVENT_PROBLEM_CREATED
    if source_value == "ai":
        return EVENT_AI_RECOMMENDATION_READY
    if source_value == "ticket":
        return EVENT_TICKET_STATUS_CHANGED
    return EVENT_SYSTEM_ALERT


def _default_source_for_event(event_type: str) -> str:
    if event_type.startswith("sla_") or event_type == EVENT_AI_SLA_RISK_HIGH:
        return "sla"
    if event_type.startswith("problem_"):
        return "problem"
    if event_type.startswith("ai_"):
        return "ai"
    if event_type.startswith("ticket_") or event_type == EVENT_MENTION:
        return "ticket"
    return "system"


def _default_cooldown_for_event(event_type: str, fallback_minutes: int) -> int:
    return int(_EVENT_DEFAULT_COOLDOWNS.get(event_type, max(1, fallback_minutes)))


def _coerce_linked_entity(metadata_json: dict | None, link: str | None) -> tuple[str | None, str | None]:
    metadata = metadata_json or {}
    entity_type = str(metadata.get("entity_type") or "").strip().lower() or None
    entity_id = str(
        metadata.get("entity_id")
        or metadata.get("ticket_id")
        or metadata.get("problem_id")
        or ""
    ).strip() or None
    if entity_type and entity_id:
        return entity_type, entity_id
    raw_link = str(link or "")
    ticket_match = re.search(r"/tickets/([^/?#]+)", raw_link)
    if ticket_match:
        return "ticket", ticket_match.group(1)
    problem_match = re.search(r"/problems/([^/?#]+)", raw_link)
    if problem_match:
        return "problem", problem_match.group(1)
    return entity_type, entity_id


def _compact_text(value: Any) -> str:
    text = str(value or "").strip()
    return " ".join(text.split())


def _hash_token(parts: Iterable[str]) -> str:
    digest = hashlib.sha1("|".join([part for part in parts if part]).encode("utf-8")).hexdigest()
    return digest[:16]


def _material_change_fingerprint(
    *,
    event_type: str,
    severity: str,
    body: str | None,
    metadata_json: dict | None,
    action_payload: dict | None,
) -> str:
    metadata = metadata_json or {}
    payload = action_payload or {}
    if event_type == EVENT_AI_RECOMMENDATION_READY:
        return _hash_token(
            [
                _compact_text(metadata.get("recommended_action")),
                _compact_text(metadata.get("confidence_band")),
                str(bool(metadata.get("tentative"))).lower(),
                _compact_text(metadata.get("recommendation_mode")),
            ]
        )
    if event_type in {EVENT_AI_SLA_RISK_HIGH, EVENT_SLA_AT_RISK, EVENT_SLA_BREACHED, EVENT_SLA_RECOVERED}:
        actions = metadata.get("recommended_actions") or metadata.get("next_best_actions") or []
        return _hash_token(
            [
                _compact_text(metadata.get("band") or metadata.get("risk_band") or severity),
                *(str(item).strip().lower() for item in list(actions)[:2]),
                str(bool(metadata.get("is_breached"))).lower(),
            ]
        )
    if event_type in {EVENT_TICKET_ASSIGNED, EVENT_TICKET_REASSIGNED}:
        return _hash_token(
            [
                _compact_text(metadata.get("old_assignee")),
                _compact_text(metadata.get("new_assignee") or payload.get("assignee")),
                severity,
            ]
        )
    if event_type in {EVENT_TICKET_STATUS_CHANGED, EVENT_TICKET_RESOLVED}:
        return _hash_token(
            [
                _compact_text(metadata.get("status_from")),
                _compact_text(metadata.get("status_to")),
                _compact_text(metadata.get("comment_id")),
            ]
        )
    if event_type in {EVENT_TICKET_COMMENTED, EVENT_MENTION}:
        return _hash_token([_compact_text(metadata.get("comment_id")), _compact_text(body)])
    if event_type in {EVENT_PROBLEM_CREATED, EVENT_PROBLEM_LINKED}:
        return _hash_token(
            [
                _compact_text(metadata.get("problem_id")),
                _compact_text(metadata.get("ticket_id")),
                severity,
            ]
        )
    return _hash_token([severity, _compact_text(body), _compact_text(metadata.get("reason"))])


def _build_dedupe_key(
    *,
    event_type: str,
    link: str | None,
    severity: str,
    metadata_json: dict | None,
    action_payload: dict | None,
    body: str | None,
) -> str:
    entity_type, entity_id = _coerce_linked_entity(metadata_json, link)
    fingerprint = _material_change_fingerprint(
        event_type=event_type,
        severity=severity,
        body=body,
        metadata_json=metadata_json,
        action_payload=action_payload,
    )
    if entity_type and entity_id:
        return f"{entity_type}:{entity_id}:{event_type}:{fingerprint}"
    return f"{event_type}:{fingerprint}"


def _notification_event_enabled(pref: NotificationPreference, *, event_type: str) -> bool:
    field_name = _EVENT_PREF_FIELDS.get(event_type)
    if not field_name:
        return True
    return bool(getattr(pref, field_name, True))


def _event_supports_digest(event_type: str, severity: str) -> bool:
    return event_type in _DIGEST_FRIENDLY_EVENTS or severity in {"medium", "warning", "high"}


def _should_send_immediate_email_for_event(
    *,
    pref: NotificationPreference,
    event_type: str,
    severity: str,
) -> bool:
    if event_type in _IMMEDIATE_EMAIL_EVENTS:
        return True
    if event_type in {EVENT_TICKET_ASSIGNED, EVENT_TICKET_REASSIGNED, EVENT_PROBLEM_LINKED}:
        threshold = str(pref.immediate_email_min_severity or pref.email_min_severity or "high").lower()
        return _severity_ge(severity, threshold)
    if event_type == EVENT_AI_SLA_RISK_HIGH:
        return _severity_ge(severity, "high")
    return False


def get_or_create_notification_preference(db: Session, *, user_id: UUID) -> NotificationPreference:
    pref = db.get(NotificationPreference, user_id)
    if pref:
        return pref
    pref = NotificationPreference(user_id=user_id)
    db.add(pref)
    db.flush()
    return pref


def update_notification_preference(
    db: Session,
    *,
    user_id: UUID,
    email_enabled: bool | None = None,
    email_min_severity: str | None = None,
    immediate_email_min_severity: str | None = None,
    digest_enabled: bool | None = None,
    digest_frequency: str | None = None,
    quiet_hours_enabled: bool | None = None,
    quiet_hours_start: str | None = None,
    quiet_hours_end: str | None = None,
    critical_bypass_quiet_hours: bool | None = None,
    ticket_assignment_enabled: bool | None = None,
    ticket_comment_enabled: bool | None = None,
    sla_notifications_enabled: bool | None = None,
    problem_notifications_enabled: bool | None = None,
    ai_notifications_enabled: bool | None = None,
) -> NotificationPreference:
    pref = get_or_create_notification_preference(db, user_id=user_id)
    if email_enabled is not None:
        pref.email_enabled = bool(email_enabled)
    if email_min_severity is not None:
        pref.email_min_severity = str(email_min_severity or "critical").lower()
    if immediate_email_min_severity is not None:
        pref.immediate_email_min_severity = str(immediate_email_min_severity or "high").lower()
    elif email_min_severity is not None and not str(pref.immediate_email_min_severity or "").strip():
        pref.immediate_email_min_severity = str(email_min_severity or "high").lower()
    if digest_enabled is not None:
        pref.digest_enabled = bool(digest_enabled)
    if digest_frequency is not None:
        pref.digest_frequency = str(digest_frequency or "hourly").lower()
    if quiet_hours_enabled is not None:
        pref.quiet_hours_enabled = bool(quiet_hours_enabled)
    if quiet_hours_start is not None:
        pref.quiet_hours_start = _parse_time(quiet_hours_start)
    if quiet_hours_end is not None:
        pref.quiet_hours_end = _parse_time(quiet_hours_end)
    if critical_bypass_quiet_hours is not None:
        pref.critical_bypass_quiet_hours = bool(critical_bypass_quiet_hours)
    if ticket_assignment_enabled is not None:
        pref.ticket_assignment_enabled = bool(ticket_assignment_enabled)
    if ticket_comment_enabled is not None:
        pref.ticket_comment_enabled = bool(ticket_comment_enabled)
    if sla_notifications_enabled is not None:
        pref.sla_notifications_enabled = bool(sla_notifications_enabled)
    if problem_notifications_enabled is not None:
        pref.problem_notifications_enabled = bool(problem_notifications_enabled)
    if ai_notifications_enabled is not None:
        pref.ai_notifications_enabled = bool(ai_notifications_enabled)
    pref.updated_at = utcnow()
    db.add(pref)
    db.commit()
    db.refresh(pref)
    return pref


def serialize_notification_preference(pref: NotificationPreference) -> dict:
    return {
        "email_enabled": bool(pref.email_enabled),
        "email_min_severity": str(pref.email_min_severity or "critical"),
        "immediate_email_min_severity": str(
            pref.immediate_email_min_severity or pref.email_min_severity or "high"
        ),
        "digest_enabled": bool(getattr(pref, "digest_enabled", True)),
        "digest_frequency": str(pref.digest_frequency or "hourly"),
        "quiet_hours_enabled": bool(getattr(pref, "quiet_hours_enabled", False)),
        "quiet_hours_start": _format_time(pref.quiet_hours_start),
        "quiet_hours_end": _format_time(pref.quiet_hours_end),
        "critical_bypass_quiet_hours": bool(getattr(pref, "critical_bypass_quiet_hours", True)),
        "ticket_assignment_enabled": bool(getattr(pref, "ticket_assignment_enabled", True)),
        "ticket_comment_enabled": bool(getattr(pref, "ticket_comment_enabled", True)),
        "sla_notifications_enabled": bool(getattr(pref, "sla_notifications_enabled", True)),
        "problem_notifications_enabled": bool(getattr(pref, "problem_notifications_enabled", True)),
        "ai_notifications_enabled": bool(getattr(pref, "ai_notifications_enabled", True)),
    }


def log_delivery_event(
    db: Session,
    *,
    notification_id: UUID,
    user_id: UUID | None,
    workflow_name: str | None,
    trace_id: str | None,
    recipients: list[str] | None,
    duplicate_suppression: str | None,
    delivery_status: str,
    error: str | None = None,
) -> NotificationDeliveryEvent:
    event = NotificationDeliveryEvent(
        notification_id=notification_id,
        user_id=user_id,
        workflow_name=workflow_name,
        trace_id=trace_id,
        recipients_json=recipients or [],
        duplicate_suppression=duplicate_suppression,
        delivery_status=delivery_status,
        error=error,
    )
    db.add(event)
    db.flush()
    return event


def _n8n_workflow_name_for_notification(notification: Notification) -> str | None:
    if notification.metadata_json and notification.metadata_json.get("workflow_name"):
        return str(notification.metadata_json.get("workflow_name") or "").strip() or None
    event_type = _normalize_event_type(notification.event_type, source=notification.source)
    if str(notification.source or "").strip().lower() == "n8n":
        return None
    return _N8N_WORKFLOW_BY_EVENT.get(event_type)


def _dispatch_n8n_notification(
    *,
    notification: Notification,
    user: User,
) -> tuple[bool, str | None]:
    workflow_name = _n8n_workflow_name_for_notification(notification)
    base = str(settings.N8N_WEBHOOK_BASE_URL or "").strip().rstrip("/")
    if not workflow_name or not base:
        return False, "n8n_unavailable"
    payload = {
        "notification_id": str(notification.id),
        "event_type": notification.event_type,
        "title": notification.title,
        "body": notification.body,
        "severity": notification.severity,
        "source": notification.source,
        "link": notification.link,
        "recipient": {
            "user_id": str(user.id),
            "email": user.email,
            "name": user.name,
        },
        "metadata": notification.metadata_json or {},
        "action_payload": notification.action_payload or {},
    }
    headers = {"Content-Type": "application/json"}
    secret = str(settings.AUTOMATION_SECRET or "").strip()
    if secret:
        headers["X-Automation-Secret"] = secret
    try:
        with httpx.Client(timeout=5.0) as client:
            response = client.post(f"{base}/{workflow_name.lstrip('/')}", json=payload, headers=headers)
            if response.status_code >= 400:
                logger.warning(
                    "Notification n8n delivery failed workflow=%s status=%s body=%s",
                    workflow_name,
                    response.status_code,
                    response.text[:300],
                )
                return False, f"n8n_http_{response.status_code}"
    except Exception as exc:  # noqa: BLE001
        logger.warning("Notification n8n delivery failed workflow=%s error=%s", workflow_name, exc)
        return False, str(exc)
    return True, None


def route_notification_delivery(
    db: Session,
    *,
    notification: Notification,
    user: User,
    force_email: bool = False,
) -> tuple[str, str]:
    pref = get_or_create_notification_preference(db, user_id=user.id)
    event_type = _normalize_event_type(notification.event_type, source=notification.source)
    severity = str(notification.severity or "info").lower()
    now = utcnow()
    quiet_hours = bool(getattr(pref, "quiet_hours_enabled", False)) and _is_now_in_quiet_hours(
        now,
        pref.quiet_hours_start,
        pref.quiet_hours_end,
    )
    bypass_quiet_hours = bool(getattr(pref, "critical_bypass_quiet_hours", True)) and (
        _severity_ge(severity, "critical") or event_type in {EVENT_SLA_BREACHED, EVENT_PROBLEM_CREATED, EVENT_SYSTEM_ALERT}
    )

    if force_email:
        return ROUTE_DIRECT_EMAIL, "forced_email"
    if not user.email or not pref.email_enabled:
        return ROUTE_IN_APP_ONLY, "email_disabled"

    workflow_name = _n8n_workflow_name_for_notification(notification)
    if workflow_name and (not quiet_hours or bypass_quiet_hours):
        return ROUTE_N8N_WORKFLOW, "workflow_route"
    if quiet_hours and not bypass_quiet_hours:
        if bool(getattr(pref, "digest_enabled", True)) and _event_supports_digest(event_type, severity):
            return ROUTE_DIGEST_QUEUE, "quiet_hours_digest"
        return ROUTE_IN_APP_ONLY, "quiet_hours"
    if _should_send_immediate_email_for_event(pref=pref, event_type=event_type, severity=severity):
        return ROUTE_DIRECT_EMAIL, "eligible_immediate"
    if bool(getattr(pref, "digest_enabled", True)) and _event_supports_digest(event_type, severity):
        return ROUTE_DIGEST_QUEUE, "digest_queue"
    return ROUTE_IN_APP_ONLY, "in_app_only"


def dispatch_email_for_notification(
    db: Session,
    *,
    notification: Notification,
    user: User,
    force: bool = False,
) -> tuple[bool, str]:
    if not user.email:
        log_delivery_event(
            db,
            notification_id=notification.id,
            user_id=user.id,
            workflow_name=(notification.metadata_json or {}).get("workflow_name") if notification.metadata_json else None,
            trace_id=(notification.metadata_json or {}).get("trace_id") if notification.metadata_json else None,
            recipients=[user.email] if user.email else [],
            duplicate_suppression=None,
            delivery_status="email-failed",
            error="missing_user_email",
        )
        return False, "missing_user_email"

    route, reason = route_notification_delivery(db, notification=notification, user=user, force_email=force)
    if route != ROUTE_DIRECT_EMAIL:
        status = "pending-digest" if route == ROUTE_DIGEST_QUEUE else "in-app"
        log_delivery_event(
            db,
            notification_id=notification.id,
            user_id=user.id,
            workflow_name=(notification.metadata_json or {}).get("workflow_name") if notification.metadata_json else None,
            trace_id=(notification.metadata_json or {}).get("trace_id") if notification.metadata_json else None,
            recipients=[user.email],
            duplicate_suppression=reason,
            delivery_status=status,
        )
        return False, reason

    ok, error = deliver_notification_email(
        user_email=user.email,
        notification=notification,
        frontend_base_url=settings.FRONTEND_BASE_URL,
    )
    log_delivery_event(
        db,
        notification_id=notification.id,
        user_id=user.id,
        workflow_name=(notification.metadata_json or {}).get("workflow_name") if notification.metadata_json else None,
        trace_id=(notification.metadata_json or {}).get("trace_id") if notification.metadata_json else None,
        recipients=[user.email],
        duplicate_suppression=None,
        delivery_status="email-sent" if ok else "email-failed",
        error=error,
    )
    return ok, error or ""


def dispatch_notification_delivery(
    db: Session,
    *,
    notification: Notification,
    user: User,
) -> tuple[bool, str]:
    route, reason = route_notification_delivery(db, notification=notification, user=user)
    workflow_name = (notification.metadata_json or {}).get("workflow_name") if notification.metadata_json else None
    trace_id = (notification.metadata_json or {}).get("trace_id") if notification.metadata_json else None
    recipients = [user.email] if user.email else []

    if route == ROUTE_IN_APP_ONLY:
        log_delivery_event(
            db,
            notification_id=notification.id,
            user_id=user.id,
            workflow_name=workflow_name,
            trace_id=trace_id,
            recipients=recipients,
            duplicate_suppression=reason,
            delivery_status="in-app",
        )
        return True, reason

    if route == ROUTE_DIGEST_QUEUE:
        log_delivery_event(
            db,
            notification_id=notification.id,
            user_id=user.id,
            workflow_name=workflow_name,
            trace_id=trace_id,
            recipients=recipients,
            duplicate_suppression=reason,
            delivery_status="pending-digest",
        )
        return True, reason

    if route == ROUTE_N8N_WORKFLOW:
        ok, error = _dispatch_n8n_notification(notification=notification, user=user)
        log_delivery_event(
            db,
            notification_id=notification.id,
            user_id=user.id,
            workflow_name=_n8n_workflow_name_for_notification(notification) or workflow_name,
            trace_id=trace_id,
            recipients=recipients,
            duplicate_suppression=None,
            delivery_status="n8n-sent" if ok else "n8n-failed",
            error=error,
        )
        if ok:
            return True, "n8n_sent"
        if _severity_ge(str(notification.severity or "info").lower(), "high"):
            fallback_ok, fallback_reason = dispatch_email_for_notification(
                db,
                notification=notification,
                user=user,
                force=True,
            )
            return fallback_ok, fallback_reason or error or "n8n_failed_fallback_email"
        return False, error or "n8n_failed"

    ok, error = dispatch_email_for_notification(db, notification=notification, user=user, force=True)
    return ok, error or ""

def list_notifications(
    db: Session,
    *,
    user_id: UUID,
    unread_only: bool = False,
    source: str | None = None,
    severity: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[Notification]:
    query = db.query(Notification).filter(Notification.user_id == user_id)
    if unread_only:
        query = query.filter(Notification.read_at.is_(None))
    normalized_source = (source or "").strip().lower()
    if normalized_source:
        query = query.filter(Notification.source == normalized_source)
    normalized_severity = (severity or "").strip().lower()
    if normalized_severity:
        query = query.filter(Notification.severity == normalized_severity)
    return query.order_by(Notification.created_at.desc()).offset(max(0, offset)).limit(limit).all()


def count_unread_notifications(db: Session, *, user_id: UUID) -> int:
    return db.query(Notification).filter(Notification.user_id == user_id, Notification.read_at.is_(None)).count()


def create_notification(
    db: Session,
    *,
    user_id: UUID,
    title: str,
    body: str | None = None,
    severity: str = "info",
    link: str | None = None,
    source: str | None = None,
    event_type: str | None = None,
    metadata_json: dict | None = None,
    action_type: str | None = None,
    action_payload: dict | None = None,
    dedupe_key: str | None = None,
    pinned_until_read: bool | None = None,
) -> Notification:
    normalized_event_type = _normalize_event_type(event_type, source=source)
    normalized_source = str(source or "").strip().lower() or _default_source_for_event(normalized_event_type)
    metadata = dict(metadata_json or {})
    entity_type, entity_id = _coerce_linked_entity(metadata, link)
    if entity_type:
        metadata.setdefault("entity_type", entity_type)
    if entity_id:
        metadata.setdefault("entity_id", entity_id)
    record = Notification(
        user_id=user_id,
        title=title,
        body=body,
        severity=str(severity or "info").lower(),
        event_type=normalized_event_type,
        link=link,
        source=normalized_source,
        dedupe_key=dedupe_key
        or _build_dedupe_key(
            event_type=normalized_event_type,
            link=link,
            severity=str(severity or "info").lower(),
            metadata_json=metadata,
            action_payload=action_payload,
            body=body,
        ),
        metadata_json=metadata,
        action_type=action_type,
        action_payload=action_payload,
        pinned_until_read=bool(pinned_until_read)
        if pinned_until_read is not None
        else normalized_event_type in _PINNED_EVENT_TYPES or _severity_ge(str(severity or "info").lower(), "critical"),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    user = db.get(User, user_id)
    if user:
        pref = get_or_create_notification_preference(db, user_id=user.id)
        if _notification_event_enabled(pref, event_type=record.event_type):
            dispatch_notification_delivery(db, notification=record, user=user)
        db.commit()
    return record


def mark_notification_as_read(
    db: Session,
    *,
    user_id: UUID,
    notification_id: UUID,
) -> Notification | None:
    record = db.get(Notification, notification_id)
    if not record or record.user_id != user_id:
        return None
    if record.read_at is None:
        record.read_at = utcnow()
        db.commit()
        db.refresh(record)
    return record


def mark_notification_as_unread(
    db: Session,
    *,
    user_id: UUID,
    notification_id: UUID,
) -> Notification | None:
    record = db.get(Notification, notification_id)
    if not record or record.user_id != user_id:
        return None
    if record.read_at is not None:
        record.read_at = None
        db.commit()
        db.refresh(record)
    return record


def mark_all_notifications_as_read(db: Session, *, user_id: UUID) -> int:
    now = utcnow()
    updated = (
        db.query(Notification)
        .filter(
            Notification.user_id == user_id,
            Notification.read_at.is_(None),
            Notification.pinned_until_read.is_(False),
        )
        .update({"read_at": now}, synchronize_session=False)
    )
    db.commit()
    return int(updated or 0)


def delete_notification(
    db: Session,
    *,
    user_id: UUID,
    notification_id: UUID,
) -> bool:
    record = db.get(Notification, notification_id)
    if not record or record.user_id != user_id:
        return False
    db.delete(record)
    db.commit()
    return True


def _find_user_by_identity(db: Session, identity: str | None) -> User | None:
    value = str(identity or "").strip()
    if not value:
        return None
    normalized = value.casefold()
    return db.execute(
        select(User).where((User.email.ilike(normalized)) | (User.name.ilike(normalized)))
    ).scalars().first()


def resolve_ticket_recipients(db: Session, *, ticket: Ticket, include_admins: bool = True) -> list[User]:
    recipients_by_id: dict[str, User] = {}

    if include_admins:
        admins = db.execute(select(User).where(User.role == UserRole.admin)).scalars().all()
        for admin in admins:
            recipients_by_id[str(admin.id)] = admin

    if str(ticket.reporter_id or "").strip():
        reporter_user = db.get(User, ticket.reporter_id)
        if reporter_user:
            recipients_by_id[str(reporter_user.id)] = reporter_user

    assignee_user = _find_user_by_identity(db, ticket.assignee)
    if assignee_user:
        recipients_by_id[str(assignee_user.id)] = assignee_user

    reporter_name_user = _find_user_by_identity(db, ticket.reporter)
    if reporter_name_user:
        recipients_by_id[str(reporter_name_user.id)] = reporter_name_user

    return list(recipients_by_id.values())


def resolve_problem_recipients(db: Session, *, problem: Problem, include_admins: bool = True) -> list[User]:
    recipients_by_id: dict[str, User] = {}

    if include_admins:
        admins = db.execute(select(User).where(User.role == UserRole.admin)).scalars().all()
        for admin in admins:
            recipients_by_id[str(admin.id)] = admin

    linked_tickets = db.execute(select(Ticket).where(Ticket.problem_id == problem.id)).scalars().all()
    for ticket in linked_tickets:
        for user in resolve_ticket_recipients(db, ticket=ticket, include_admins=False):
            recipients_by_id[str(user.id)] = user
    return list(recipients_by_id.values())


def resolve_comment_mentions(db: Session, *, text: str) -> list[User]:
    users: dict[str, User] = {}
    for token in _MENTION_PATTERN.findall(text or ""):
        matched = _find_user_by_identity(db, token)
        if matched:
            users[str(matched.id)] = matched
    return list(users.values())


def _ticket_stakeholders(
    db: Session,
    *,
    ticket: Ticket,
    include_assignee: bool = True,
    include_reporter: bool = True,
    include_admins: bool = False,
) -> list[User]:
    users: dict[str, User] = {}
    if include_admins:
        for admin in db.execute(select(User).where(User.role == UserRole.admin)).scalars().all():
            users[str(admin.id)] = admin
    if include_assignee:
        assignee_user = _find_user_by_identity(db, ticket.assignee)
        if assignee_user:
            users[str(assignee_user.id)] = assignee_user
    if include_reporter:
        if str(ticket.reporter_id or "").strip():
            reporter_user = db.get(User, ticket.reporter_id)
            if reporter_user:
                users[str(reporter_user.id)] = reporter_user
        reporter_name_user = _find_user_by_identity(db, ticket.reporter)
        if reporter_name_user:
            users[str(reporter_name_user.id)] = reporter_name_user
    return list(users.values())


def _filter_recipients_for_event(
    db: Session,
    *,
    users: list[User],
    event_type: str,
) -> list[User]:
    filtered: list[User] = []
    for user in users:
        pref = get_or_create_notification_preference(db, user_id=user.id)
        if _notification_event_enabled(pref, event_type=event_type):
            filtered.append(user)
    return filtered


def _recent_unread_duplicate_exists(
    db: Session,
    *,
    user_id: UUID,
    event_type: str,
    dedupe_key: str,
    severity: str,
    created_after: dt.datetime,
) -> UUID | None:
    existing = db.execute(
        select(Notification.id).where(
            Notification.user_id == user_id,
            Notification.event_type == event_type,
            Notification.dedupe_key == dedupe_key,
            Notification.severity == severity,
            Notification.read_at.is_(None),
            Notification.created_at >= created_after,
        )
    ).scalars().first()
    return existing


def create_notifications_for_users(
    db: Session,
    *,
    users: list[User],
    title: str,
    body: str | None,
    severity: str,
    link: str,
    source: str,
    cooldown_minutes: int = 60,
    metadata_json: dict | None = None,
    action_type: str | None = None,
    action_payload: dict | None = None,
    event_type: str | None = None,
    pinned_until_read: bool | None = None,
) -> list[Notification]:
    if not users:
        return []
    normalized_event_type = _normalize_event_type(event_type, source=source)
    normalized_source = str(source or "").strip().lower() or _default_source_for_event(normalized_event_type)
    metadata = dict(metadata_json or {})
    entity_type, entity_id = _coerce_linked_entity(metadata, link)
    if entity_type:
        metadata.setdefault("entity_type", entity_type)
    if entity_id:
        metadata.setdefault("entity_id", entity_id)
    dedupe_key = _build_dedupe_key(
        event_type=normalized_event_type,
        link=link,
        severity=str(severity or "info").lower(),
        metadata_json=metadata,
        action_payload=action_payload,
        body=body,
    )
    now = utcnow()
    cutoff = now - dt.timedelta(minutes=_default_cooldown_for_event(normalized_event_type, cooldown_minutes))
    created: list[Notification] = []
    eligible_users = _filter_recipients_for_event(db, users=users, event_type=normalized_event_type)
    for user in eligible_users:
        existing = _recent_unread_duplicate_exists(
            db,
            user_id=user.id,
            event_type=normalized_event_type,
            dedupe_key=dedupe_key,
            severity=str(severity or "info").lower(),
            created_after=cutoff,
        )
        if existing:
            log_delivery_event(
                db,
                notification_id=existing,
                user_id=user.id,
                workflow_name=(metadata or {}).get("workflow_name") if isinstance(metadata, dict) else None,
                trace_id=(metadata or {}).get("trace_id") if isinstance(metadata, dict) else None,
                recipients=[user.email] if user.email else [],
                duplicate_suppression="duplicate_within_cooldown",
                delivery_status="suppressed",
            )
            continue
        record = Notification(
            user_id=user.id,
            title=title,
            body=body,
            severity=str(severity or "info").lower(),
            event_type=normalized_event_type,
            link=link,
            source=normalized_source,
            dedupe_key=dedupe_key,
            metadata_json=metadata,
            action_type=action_type,
            action_payload=action_payload,
            pinned_until_read=bool(pinned_until_read)
            if pinned_until_read is not None
            else normalized_event_type in _PINNED_EVENT_TYPES or _severity_ge(str(severity or "info").lower(), "critical"),
        )
        db.add(record)
        created.append(record)
    if created:
        db.flush()
        for record in created:
            user = next((u for u in eligible_users if u.id == record.user_id), None)
            if user:
                dispatch_notification_delivery(db, notification=record, user=user)
    return created


def notify_ticket_assignment_change(
    db: Session,
    *,
    ticket: Ticket,
    previous_assignee: str | None,
    actor: str | None,
    notify_previous_assignee: bool = True,
) -> list[Notification]:
    new_assignee_user = _find_user_by_identity(db, ticket.assignee)
    previous_assignee_user = _find_user_by_identity(db, previous_assignee)
    created: list[Notification] = []
    metadata = {
        "ticket_id": ticket.id,
        "ticket_title": ticket.title,
        "old_assignee": previous_assignee,
        "new_assignee": ticket.assignee,
        "actor": actor,
    }
    priority_value = str(getattr(ticket.priority, "value", ticket.priority)).lower()
    severity = "high" if priority_value in {"high", "critical"} else "warning"
    if new_assignee_user and (not previous_assignee_user or new_assignee_user.id != previous_assignee_user.id):
        event_type = EVENT_TICKET_REASSIGNED if str(previous_assignee or "").strip() else EVENT_TICKET_ASSIGNED
        title = f"Ticket assigned: {ticket.id}" if event_type == EVENT_TICKET_ASSIGNED else f"Ticket reassigned: {ticket.id}"
        body = (
            f"You are now responsible for '{ticket.title}'."
            if event_type == EVENT_TICKET_ASSIGNED
            else f"Ticket '{ticket.title}' was reassigned to you by {actor or 'the team'}."
        )
        created.extend(
            create_notifications_for_users(
                db,
                users=[new_assignee_user],
                title=title,
                body=body,
                severity=severity,
                link=f"/tickets/{ticket.id}",
                source="ticket",
                cooldown_minutes=20,
                metadata_json=metadata,
                action_type="view",
                action_payload={"ticket_id": ticket.id},
                event_type=event_type,
            )
        )
    if notify_previous_assignee and previous_assignee_user and new_assignee_user and previous_assignee_user.id != new_assignee_user.id:
        created.extend(
            create_notifications_for_users(
                db,
                users=[previous_assignee_user],
                title=f"Ticket reassigned: {ticket.id}",
                body=f"Ticket '{ticket.title}' has been reassigned away from you.",
                severity="warning",
                link=f"/tickets/{ticket.id}",
                source="ticket",
                cooldown_minutes=20,
                metadata_json=metadata,
                action_type="view",
                action_payload={"ticket_id": ticket.id},
                event_type=EVENT_TICKET_REASSIGNED,
            )
        )
    return created


def notify_ticket_comment(
    db: Session,
    *,
    ticket: Ticket,
    comment_text: str,
    comment_id: str | None,
    actor: str | None,
) -> list[Notification]:
    actor_normalized = str(actor or "").strip().casefold()
    mentions = resolve_comment_mentions(db, text=comment_text)
    stakeholders = [
        user
        for user in _ticket_stakeholders(db, ticket=ticket, include_assignee=True, include_reporter=True, include_admins=False)
        if user.name.strip().casefold() != actor_normalized and user.email.strip().casefold() != actor_normalized
    ]
    mention_ids = {user.id for user in mentions}
    regular_watchers = [user for user in stakeholders if user.id not in mention_ids]
    metadata = {
        "ticket_id": ticket.id,
        "ticket_title": ticket.title,
        "comment_id": comment_id,
        "actor": actor,
    }
    created: list[Notification] = []
    if regular_watchers:
        priority_value = str(getattr(ticket.priority, "value", ticket.priority)).lower()
        created.extend(
            create_notifications_for_users(
                db,
                users=regular_watchers,
                title=f"New comment on {ticket.id}",
                body=f"{actor or 'A teammate'} added a comment on '{ticket.title}'.",
                severity="warning" if priority_value in {"high", "critical"} else "info",
                link=f"/tickets/{ticket.id}",
                source="ticket",
                cooldown_minutes=10,
                metadata_json=metadata,
                action_type="view",
                action_payload={"ticket_id": ticket.id, "comment_id": comment_id},
                event_type=EVENT_TICKET_COMMENTED,
            )
        )
    if mentions:
        created.extend(
            create_notifications_for_users(
                db,
                users=[user for user in mentions if user.name.strip().casefold() != actor_normalized],
                title=f"You were mentioned on {ticket.id}",
                body=f"{actor or 'A teammate'} mentioned you in a ticket comment.",
                severity="high" if str(getattr(ticket.priority, "value", ticket.priority)).lower() in {"high", "critical"} else "warning",
                link=f"/tickets/{ticket.id}",
                source="ticket",
                cooldown_minutes=5,
                metadata_json={**metadata, "mentioned_users": [user.name for user in mentions]},
                action_type="view",
                action_payload={"ticket_id": ticket.id, "comment_id": comment_id},
                event_type=EVENT_MENTION,
            )
        )
    return created


def notify_ticket_status_change(
    db: Session,
    *,
    ticket: Ticket,
    previous_status: str | None,
    actor: str | None,
    comment_id: str | None = None,
) -> list[Notification]:
    actor_normalized = str(actor or "").strip().casefold()
    recipients = [
        user
        for user in _ticket_stakeholders(db, ticket=ticket, include_assignee=True, include_reporter=True, include_admins=False)
        if user.name.strip().casefold() != actor_normalized and user.email.strip().casefold() != actor_normalized
    ]
    if not recipients:
        return []

    status_to = str(getattr(ticket.status, "value", ticket.status) or "").strip().lower()
    previous_value = str(previous_status or "").strip().lower()
    event_type = EVENT_TICKET_RESOLVED if status_to in {"resolved", "closed"} else EVENT_TICKET_STATUS_CHANGED
    priority_value = str(getattr(ticket.priority, "value", ticket.priority)).lower()
    severity = "warning" if event_type == EVENT_TICKET_RESOLVED and priority_value in {"high", "critical"} else "info"
    title = f"Ticket resolved: {ticket.id}" if event_type == EVENT_TICKET_RESOLVED else f"Ticket status changed: {ticket.id}"
    body = (
        f"Ticket '{ticket.title}' moved from {previous_value or 'unknown'} to {status_to}."
        if event_type == EVENT_TICKET_STATUS_CHANGED
        else f"Ticket '{ticket.title}' is now {status_to}."
    )
    return create_notifications_for_users(
        db,
        users=recipients,
        title=title,
        body=body,
        severity=severity,
        link=f"/tickets/{ticket.id}",
        source="ticket",
        cooldown_minutes=20,
        metadata_json={
            "ticket_id": ticket.id,
            "ticket_title": ticket.title,
            "status_from": previous_value,
            "status_to": status_to,
            "comment_id": comment_id,
            "actor": actor,
        },
        action_type="view",
        action_payload={"ticket_id": ticket.id},
        event_type=event_type,
    )


def notify_ticket_problem_link(
    db: Session,
    *,
    ticket: Ticket,
    problem_id: str,
) -> list[Notification]:
    recipients = _ticket_stakeholders(db, ticket=ticket, include_assignee=True, include_reporter=True, include_admins=False)
    if not recipients:
        return []
    severity = "high" if str(getattr(ticket.priority, "value", ticket.priority)).lower() in {"high", "critical"} else "info"
    return create_notifications_for_users(
        db,
        users=recipients,
        title=f"Known problem linked: {ticket.id}",
        body=f"Ticket '{ticket.title}' is linked to problem {problem_id}.",
        severity=severity,
        link=f"/tickets/{ticket.id}",
        source="problem",
        cooldown_minutes=60,
        metadata_json={
            "ticket_id": ticket.id,
            "ticket_title": ticket.title,
            "problem_id": problem_id,
        },
        action_type="view",
        action_payload={"ticket_id": ticket.id, "problem_id": problem_id},
        event_type=EVENT_PROBLEM_LINKED,
    )


def run_hourly_high_digest(db: Session) -> dict[str, int]:
    now = utcnow()
    since = now - dt.timedelta(hours=1)
    rows = db.execute(
        select(Notification).where(
            Notification.read_at.is_(None),
            Notification.created_at >= since,
        )
    ).scalars().all()
    if not rows:
        return {"users": 0, "emails_sent": 0}

    grouped: dict[UUID, list[Notification]] = {}
    for item in rows:
        grouped.setdefault(item.user_id, []).append(item)

    sent = 0
    for user_id, items in grouped.items():
        user = db.get(User, user_id)
        if not user or not user.email:
            continue
        pref = get_or_create_notification_preference(db, user_id=user_id)
        if (
            not pref.email_enabled
            or not bool(getattr(pref, "digest_enabled", True))
            or str(pref.digest_frequency or "hourly").lower() != "hourly"
        ):
            continue
        digest_items = [
            item
            for item in items
            if route_notification_delivery(db, notification=item, user=user)[0] == ROUTE_DIGEST_QUEUE
        ]
        if not digest_items:
            continue
        ok, err = deliver_notification_email(
            user_email=user.email,
            notification=None,
            frontend_base_url=settings.FRONTEND_BASE_URL,
            digest_items=digest_items,
        )
        status = "digest-sent" if ok else "digest-failed"
        for n in digest_items:
            log_delivery_event(
                db,
                notification_id=n.id,
                user_id=user.id,
                workflow_name=(n.metadata_json or {}).get("workflow_name") if n.metadata_json else None,
                trace_id=(n.metadata_json or {}).get("trace_id") if n.metadata_json else None,
                recipients=[user.email],
                duplicate_suppression=None,
                delivery_status=status if ok else "email-failed",
                error=err,
            )
        if ok:
            sent += 1
    db.commit()
    return {"users": len(grouped), "emails_sent": sent}


def list_notification_debug_recent(
    db: Session,
    *,
    workflow: str | None = None,
    user_id: UUID | None = None,
    delivery_status: str | None = None,
    limit: int = 20,
) -> list[dict]:
    query = (
        select(NotificationDeliveryEvent, Notification)
        .join(Notification, Notification.id == NotificationDeliveryEvent.notification_id)
        .order_by(NotificationDeliveryEvent.created_at.desc())
        .limit(max(1, min(limit, 100)))
    )
    if workflow:
        query = query.where(NotificationDeliveryEvent.workflow_name == workflow)
    if user_id:
        query = query.where(Notification.user_id == user_id)
    if delivery_status:
        query = query.where(NotificationDeliveryEvent.delivery_status == delivery_status)

    rows = db.execute(query).all()
    out: list[dict] = []
    for evt, n in rows:
        out.append(
            {
                "notification_id": n.id,
                "user_id": n.user_id,
                "title": n.title,
                "severity": n.severity,
                "event_type": n.event_type,
                "source": n.source,
                "workflow_name": evt.workflow_name,
                "trace_id": evt.trace_id,
                "recipients": list(evt.recipients_json or []),
                "duplicate_suppression": evt.duplicate_suppression,
                "delivery_status": evt.delivery_status,
                "created_at": evt.created_at,
            }
        )
    return out


def notification_analytics(db: Session) -> dict:
    created_rows = db.execute(
        select(Notification.event_type, Notification.severity, func.count(Notification.id)).group_by(
            Notification.event_type,
            Notification.severity,
        )
    ).all()
    created_total: dict[str, int] = {}
    for event_type, severity, count in created_rows:
        key = f"{event_type or 'unknown'}:{severity or 'info'}"
        created_total[key] = int(count or 0)

    all_rows = db.execute(select(Notification.created_at, Notification.read_at)).all()
    within_1h = 0
    within_24h = 0
    never = 0
    total = len(all_rows)
    for created_at, read_at in all_rows:
        if read_at is None:
            never += 1
            continue
        delta = read_at - created_at
        if delta <= dt.timedelta(hours=1):
            within_1h += 1
        if delta <= dt.timedelta(hours=24):
            within_24h += 1
    read_rate = {
        "read_within_1h_pct": round((within_1h / total) * 100, 2) if total else 0.0,
        "read_within_24h_pct": round((within_24h / total) * 100, 2) if total else 0.0,
        "never_read_pct": round((never / total) * 100, 2) if total else 0.0,
    }

    delivery_rows = db.execute(
        select(NotificationDeliveryEvent.delivery_status, func.count(NotificationDeliveryEvent.id))
        .group_by(NotificationDeliveryEvent.delivery_status)
    ).all()
    delivery = {str(status): int(count or 0) for status, count in delivery_rows}
    return {
        "notifications_created_total": created_total,
        "notifications_read_rate": read_rate,
        "email_delivery_rate": delivery,
    }
