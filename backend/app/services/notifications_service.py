"""Service helpers for notifications CRUD, targeting, and read-state updates."""

from __future__ import annotations

import datetime as dt
from datetime import time as dtime
from uuid import UUID

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


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


_SEVERITY_RANK = {"low": 1, "info": 2, "medium": 2, "warning": 3, "high": 4, "critical": 5}


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
    digest_frequency: str | None = None,
    quiet_hours_start: str | None = None,
    quiet_hours_end: str | None = None,
) -> NotificationPreference:
    pref = get_or_create_notification_preference(db, user_id=user_id)
    if email_enabled is not None:
        pref.email_enabled = bool(email_enabled)
    if email_min_severity is not None:
        pref.email_min_severity = str(email_min_severity or "critical").lower()
    if digest_frequency is not None:
        pref.digest_frequency = str(digest_frequency or "hourly").lower()
    if quiet_hours_start is not None:
        pref.quiet_hours_start = _parse_time(quiet_hours_start)
    if quiet_hours_end is not None:
        pref.quiet_hours_end = _parse_time(quiet_hours_end)
    pref.updated_at = utcnow()
    db.add(pref)
    db.commit()
    db.refresh(pref)
    return pref


def serialize_notification_preference(pref: NotificationPreference) -> dict:
    return {
        "email_enabled": bool(pref.email_enabled),
        "email_min_severity": str(pref.email_min_severity or "critical"),
        "digest_frequency": str(pref.digest_frequency or "hourly"),
        "quiet_hours_start": _format_time(pref.quiet_hours_start),
        "quiet_hours_end": _format_time(pref.quiet_hours_end),
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


def _should_send_immediate_email(db: Session, *, notification: Notification, user: User) -> tuple[bool, str]:
    pref = get_or_create_notification_preference(db, user_id=user.id)
    severity = str(notification.severity or "info").lower()
    now = utcnow()
    urgent_override = severity == "critical" and str(notification.source or "").lower() == "sla"

    if not pref.email_enabled:
        return False, "email_disabled"
    if not _severity_ge(severity, pref.email_min_severity):
        return False, "below_min_severity"
    if _is_now_in_quiet_hours(now, pref.quiet_hours_start, pref.quiet_hours_end) and not urgent_override:
        return False, "quiet_hours"
    if severity == "high":
        return False, "pending-digest"
    return severity == "critical", "eligible"


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

    allowed, reason = _should_send_immediate_email(db, notification=notification, user=user)
    if not force and not allowed:
        status = "pending-digest" if reason == "pending-digest" else "in-app"
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
    metadata_json: dict | None = None,
    action_type: str | None = None,
    action_payload: dict | None = None,
) -> Notification:
    record = Notification(
        user_id=user_id,
        title=title,
        body=body,
        severity=severity,
        link=link,
        source=source,
        metadata_json=metadata_json,
        action_type=action_type,
        action_payload=action_payload,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    user = db.get(User, user_id)
    if user:
        dispatch_email_for_notification(db, notification=record, user=user)
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
        .filter(Notification.user_id == user_id, Notification.read_at.is_(None))
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


def _recent_unread_duplicate_exists(
    db: Session,
    *,
    user_id: UUID,
    source: str,
    link: str,
    title: str,
    created_after: dt.datetime,
) -> bool:
    existing = db.execute(
        select(Notification.id).where(
            Notification.user_id == user_id,
            Notification.source == source,
            Notification.link == link,
            Notification.title == title,
            Notification.read_at.is_(None),
            Notification.created_at >= created_after,
        )
    ).scalars().first()
    return existing is not None


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
) -> list[Notification]:
    if not users:
        return []
    now = utcnow()
    cutoff = now - dt.timedelta(minutes=max(1, cooldown_minutes))
    created: list[Notification] = []
    for user in users:
        if _recent_unread_duplicate_exists(
            db,
            user_id=user.id,
            source=source,
            link=link,
            title=title,
            created_after=cutoff,
        ):
            existing = db.execute(
                select(Notification.id).where(
                    Notification.user_id == user.id,
                    Notification.source == source,
                    Notification.link == link,
                    Notification.title == title,
                    Notification.read_at.is_(None),
                    Notification.created_at >= cutoff,
                )
            ).scalars().first()
            if existing:
                log_delivery_event(
                    db,
                    notification_id=existing,
                    user_id=user.id,
                    workflow_name=(metadata_json or {}).get("workflow_name") if isinstance(metadata_json, dict) else None,
                    trace_id=(metadata_json or {}).get("trace_id") if isinstance(metadata_json, dict) else None,
                    recipients=[user.email] if user.email else [],
                    duplicate_suppression="duplicate_within_cooldown",
                    delivery_status="in-app",
                )
            continue
        record = Notification(
            user_id=user.id,
            title=title,
            body=body,
            severity=severity,
            link=link,
            source=source,
            metadata_json=metadata_json,
            action_type=action_type,
            action_payload=action_payload,
        )
        db.add(record)
        created.append(record)
    if created:
        db.flush()
        for record in created:
            user = next((u for u in users if u.id == record.user_id), None)
            if user:
                dispatch_email_for_notification(db, notification=record, user=user)
    return created


def run_hourly_high_digest(db: Session) -> dict[str, int]:
    now = utcnow()
    since = now - dt.timedelta(hours=1)
    rows = db.execute(
        select(Notification).where(
            Notification.severity == "high",
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
        if not pref.email_enabled or str(pref.digest_frequency or "hourly").lower() != "hourly":
            continue
        if not _severity_ge("high", pref.email_min_severity):
            continue
        ok, err = deliver_notification_email(
            user_email=user.email,
            notification=None,
            frontend_base_url=settings.FRONTEND_BASE_URL,
            digest_items=items,
        )
        status = "email-sent" if ok else "email-failed"
        for n in items:
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
        select(Notification.source, Notification.severity, func.count(Notification.id)).group_by(Notification.source, Notification.severity)
    ).all()
    created_total: dict[str, int] = {}
    for source, severity, count in created_rows:
        key = f"{source or 'unknown'}:{severity or 'info'}"
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
