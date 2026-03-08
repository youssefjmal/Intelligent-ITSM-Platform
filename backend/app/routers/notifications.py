"""Notifications API endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, Path, Query
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_user, require_roles
from app.core.exceptions import AuthenticationException, BadRequestError, NotFoundError
from app.core.rate_limit import rate_limit
from app.db.session import get_db
from app.models.enums import UserRole
from app.models.notification import Notification
from app.models.problem import Problem
from app.models.ticket import Ticket
from app.models.user import User
from app.schemas.notification import (
    NotificationAnalyticsOut,
    NotificationCreate,
    NotificationDebugOut,
    NotificationOut,
    NotificationPreferencesOut,
    NotificationPreferencesPatch,
    NotificationUnreadCountOut,
    SystemNotificationCreate,
)
from app.services.notifications_service import (
    count_unread_notifications,
    create_notification,
    create_notifications_for_users,
    delete_notification,
    dispatch_email_for_notification,
    get_or_create_notification_preference,
    list_notifications,
    list_notification_debug_recent,
    mark_all_notifications_as_read,
    mark_notification_as_read,
    mark_notification_as_unread,
    notification_analytics,
    run_hourly_high_digest,
    resolve_problem_recipients,
    resolve_ticket_recipients,
    serialize_notification_preference,
    update_notification_preference,
)

router = APIRouter(dependencies=[Depends(rate_limit())])


@router.get("/", response_model=list[NotificationOut])
def get_notifications(
    unread_only: bool = Query(default=False),
    source: str | None = Query(default=None, description="Filter by source: n8n|system|user|sla"),
    severity: str | None = Query(default=None, description="Filter by severity: info|warning|high|critical"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[NotificationOut]:
    records = list_notifications(
        db,
        user_id=current_user.id,
        unread_only=unread_only,
        source=source,
        severity=severity,
        limit=limit,
        offset=offset,
    )
    return [NotificationOut.model_validate(record) for record in records]


@router.get("/unread-count", response_model=NotificationUnreadCountOut)
def get_unread_count(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> NotificationUnreadCountOut:
    return NotificationUnreadCountOut(count=count_unread_notifications(db, user_id=current_user.id))


@router.post("/", response_model=NotificationOut, dependencies=[Depends(require_roles(UserRole.admin, UserRole.agent))])
def post_notification(
    payload: NotificationCreate = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> NotificationOut:
    if payload.ticket_id and not db.get(Ticket, payload.ticket_id):
        raise NotFoundError("ticket_not_found", details={"ticket_id": payload.ticket_id})
    if payload.problem_id and not db.get(Problem, payload.problem_id):
        raise NotFoundError("problem_not_found", details={"problem_id": payload.problem_id})

    if payload.user_id is None and payload.ticket_id:
        ticket = db.get(Ticket, payload.ticket_id)
        if not ticket:
            raise NotFoundError("ticket_not_found", details={"ticket_id": payload.ticket_id})
        recipients = resolve_ticket_recipients(db, ticket=ticket, include_admins=True)
        records = create_notifications_for_users(
            db,
            users=recipients,
            title=payload.title,
            body=payload.body,
            severity=payload.severity,
            link=payload.link or f"/tickets/{ticket.id}",
            source=payload.source or "n8n",
            cooldown_minutes=30,
            metadata_json=payload.metadata_json,
            action_type=payload.action_type,
            action_payload=payload.action_payload,
        )
        db.commit()
        if not records:
            fallback = create_notification(
                db,
                user_id=current_user.id,
                title=payload.title,
                body=payload.body,
                severity=payload.severity,
                link=payload.link or f"/tickets/{ticket.id}",
                source=payload.source or "n8n",
                metadata_json=payload.metadata_json,
                action_type=payload.action_type,
                action_payload=payload.action_payload,
            )
            return NotificationOut.model_validate(fallback)
        db.refresh(records[0])
        return NotificationOut.model_validate(records[0])

    if payload.user_id is None and payload.problem_id:
        problem = db.get(Problem, payload.problem_id)
        if not problem:
            raise NotFoundError("problem_not_found", details={"problem_id": payload.problem_id})
        recipients = resolve_problem_recipients(db, problem=problem, include_admins=True)
        records = create_notifications_for_users(
            db,
            users=recipients,
            title=payload.title,
            body=payload.body,
            severity=payload.severity,
            link=payload.link or f"/problems/{problem.id}",
            source=payload.source or "n8n",
            cooldown_minutes=30,
            metadata_json=payload.metadata_json,
            action_type=payload.action_type,
            action_payload=payload.action_payload,
        )
        db.commit()
        if not records:
            fallback = create_notification(
                db,
                user_id=current_user.id,
                title=payload.title,
                body=payload.body,
                severity=payload.severity,
                link=payload.link or f"/problems/{problem.id}",
                source=payload.source or "n8n",
                metadata_json=payload.metadata_json,
                action_type=payload.action_type,
                action_payload=payload.action_payload,
            )
            return NotificationOut.model_validate(fallback)
        db.refresh(records[0])
        return NotificationOut.model_validate(records[0])

    target_user_id = payload.user_id or current_user.id
    if payload.user_id:
        target_user = db.get(User, payload.user_id)
        if not target_user:
            raise NotFoundError("user_not_found", details={"user_id": str(payload.user_id)})
    record = create_notification(
        db,
        user_id=target_user_id,
        title=payload.title,
        body=payload.body,
        severity=payload.severity,
        link=payload.link,
        source=payload.source or "system",
        metadata_json=payload.metadata_json,
        action_type=payload.action_type,
        action_payload=payload.action_payload,
    )
    return NotificationOut.model_validate(record)


@router.post("/{notification_id}/read", response_model=NotificationOut)
def read_notification(
    notification_id: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> NotificationOut:
    record = mark_notification_as_read(db, user_id=current_user.id, notification_id=notification_id)
    if not record:
        raise NotFoundError("notification_not_found", details={"notification_id": str(notification_id)})
    return NotificationOut.model_validate(record)


@router.patch("/{notification_id}/read", response_model=NotificationOut)
def patch_read_notification(
    notification_id: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> NotificationOut:
    record = mark_notification_as_read(db, user_id=current_user.id, notification_id=notification_id)
    if not record:
        raise NotFoundError("notification_not_found", details={"notification_id": str(notification_id)})
    return NotificationOut.model_validate(record)


@router.patch("/{notification_id}/unread", response_model=NotificationOut)
def patch_unread_notification(
    notification_id: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> NotificationOut:
    record = mark_notification_as_unread(db, user_id=current_user.id, notification_id=notification_id)
    if not record:
        raise NotFoundError("notification_not_found", details={"notification_id": str(notification_id)})
    return NotificationOut.model_validate(record)


@router.post("/read-all")
@router.post("/mark-all-read")
def read_all_notifications(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, int]:
    updated = mark_all_notifications_as_read(db, user_id=current_user.id)
    return {"updated": updated}


@router.delete("/{notification_id}")
def remove_notification(
    notification_id: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, bool]:
    deleted = delete_notification(db, user_id=current_user.id, notification_id=notification_id)
    if not deleted:
        raise NotFoundError("notification_not_found", details={"notification_id": str(notification_id)})
    return {"deleted": True}


@router.post("/system", response_model=NotificationOut, dependencies=[])
def post_system_notification(
    payload: SystemNotificationCreate = Body(...),
    x_automation_secret: str | None = Header(default=None, alias="X-Automation-Secret"),
    db: Session = Depends(get_db),
) -> NotificationOut:
    configured = settings.AUTOMATION_SECRET.strip()
    if not configured:
        raise BadRequestError("automation_secret_not_configured")
    if (x_automation_secret or "").strip() != configured:
        raise AuthenticationException("invalid_automation_secret", error_code="INVALID_AUTOMATION_SECRET", status_code=401)

    if payload.ticket_id:
        ticket = db.get(Ticket, payload.ticket_id)
        if not ticket:
            raise NotFoundError("ticket_not_found", details={"ticket_id": payload.ticket_id})
        recipients = resolve_ticket_recipients(db, ticket=ticket, include_admins=True)
        created = create_notifications_for_users(
            db,
            users=recipients,
            title=payload.title,
            body=payload.body,
            severity=payload.severity,
            link=payload.link or f"/tickets/{ticket.id}",
            source=payload.source or "n8n",
            cooldown_minutes=30,
            metadata_json=payload.metadata_json,
            action_type=payload.action_type,
            action_payload=payload.action_payload,
        )
        if not created:
            raise BadRequestError("no_notification_recipients")
        db.commit()
        db.refresh(created[0])
        return NotificationOut.model_validate(created[0])

    if payload.problem_id:
        problem = db.get(Problem, payload.problem_id)
        if not problem:
            raise NotFoundError("problem_not_found", details={"problem_id": payload.problem_id})
        recipients = resolve_problem_recipients(db, problem=problem, include_admins=True)
        created = create_notifications_for_users(
            db,
            users=recipients,
            title=payload.title,
            body=payload.body,
            severity=payload.severity,
            link=payload.link or f"/problems/{problem.id}",
            source=payload.source or "n8n",
            cooldown_minutes=30,
            metadata_json=payload.metadata_json,
            action_type=payload.action_type,
            action_payload=payload.action_payload,
        )
        if not created:
            raise BadRequestError("no_notification_recipients")
        db.commit()
        db.refresh(created[0])
        return NotificationOut.model_validate(created[0])

    target_user_id = payload.user_id
    if not target_user_id and payload.user_email:
        user = db.query(User).filter(User.email == payload.user_email).first()
        if not user:
            raise NotFoundError("user_not_found", details={"user_email": payload.user_email})
        target_user_id = user.id
    if not target_user_id and payload.user_name:
        user = db.query(User).filter(User.name.ilike(payload.user_name)).first()
        if not user:
            raise NotFoundError("user_not_found", details={"user_name": payload.user_name})
        target_user_id = user.id

    if not target_user_id:
        raise BadRequestError("user_id_or_user_email_or_user_name_required")
    if payload.user_id and not db.get(User, payload.user_id):
        raise NotFoundError("user_not_found", details={"user_id": str(payload.user_id)})

    record = create_notification(
        db,
        user_id=target_user_id,
        title=payload.title,
        body=payload.body,
        severity=payload.severity,
        link=payload.link,
        source=payload.source or "n8n",
        metadata_json=payload.metadata_json,
        action_type=payload.action_type,
        action_payload=payload.action_payload,
    )
    return NotificationOut.model_validate(record)


@router.get("/preferences", response_model=NotificationPreferencesOut)
def get_preferences(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> NotificationPreferencesOut:
    pref = get_or_create_notification_preference(db, user_id=current_user.id)
    db.commit()
    return NotificationPreferencesOut(**serialize_notification_preference(pref))


@router.patch("/preferences", response_model=NotificationPreferencesOut)
def patch_preferences(
    payload: NotificationPreferencesPatch = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> NotificationPreferencesOut:
    pref = update_notification_preference(
        db,
        user_id=current_user.id,
        email_enabled=payload.email_enabled,
        email_min_severity=payload.email_min_severity,
        digest_frequency=payload.digest_frequency,
        quiet_hours_start=payload.quiet_hours_start,
        quiet_hours_end=payload.quiet_hours_end,
    )
    return NotificationPreferencesOut(**serialize_notification_preference(pref))


@router.post("/{notification_id}/send-email", dependencies=[Depends(require_roles(UserRole.admin))])
def send_notification_email(
    notification_id: UUID = Path(...),
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> dict[str, str]:
    record = db.get(Notification, notification_id)
    if not record:
        raise NotFoundError("notification_not_found", details={"notification_id": str(notification_id)})
    user = db.get(User, record.user_id)
    if not user:
        raise NotFoundError("user_not_found", details={"user_id": str(record.user_id)})
    ok, reason = dispatch_email_for_notification(db, notification=record, user=user, force=True)
    db.commit()
    return {"status": "email-sent" if ok else "email-failed", "reason": reason or ""}


@router.post("/digest/run", dependencies=[Depends(require_roles(UserRole.admin, UserRole.agent))])
def run_digest(
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> dict[str, int]:
    return run_hourly_high_digest(db)


@router.get("/debug-recent", response_model=list[NotificationDebugOut], dependencies=[Depends(require_roles(UserRole.admin))])
def debug_recent(
    workflow: str | None = Query(default=None),
    user_id: UUID | None = Query(default=None),
    delivery_status: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> list[NotificationDebugOut]:
    rows = list_notification_debug_recent(
        db,
        workflow=workflow,
        user_id=user_id,
        delivery_status=delivery_status,
        limit=limit,
    )
    return [NotificationDebugOut(**row) for row in rows]


@router.get("/analytics", response_model=NotificationAnalyticsOut, dependencies=[Depends(require_roles(UserRole.admin, UserRole.agent))])
def analytics(
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> NotificationAnalyticsOut:
    return NotificationAnalyticsOut(**notification_analytics(db))
