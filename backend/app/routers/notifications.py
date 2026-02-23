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
from app.models.user import User
from app.schemas.notification import (
    NotificationCreate,
    NotificationOut,
    NotificationUnreadCountOut,
    SystemNotificationCreate,
)
from app.services.notifications_service import (
    count_unread_notifications,
    create_notification,
    list_notifications,
    mark_all_notifications_as_read,
    mark_notification_as_read,
)

router = APIRouter(dependencies=[Depends(rate_limit())])


@router.get("/", response_model=list[NotificationOut])
def get_notifications(
    unread_only: bool = Query(default=False),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[NotificationOut]:
    records = list_notifications(db, user_id=current_user.id, unread_only=unread_only, limit=limit)
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


@router.post("/read-all")
def read_all_notifications(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, int]:
    updated = mark_all_notifications_as_read(db, user_id=current_user.id)
    return {"updated": updated}


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

    target_user_id = payload.user_id
    if not target_user_id and payload.user_email:
        user = db.query(User).filter(User.email == payload.user_email).first()
        if not user:
            raise NotFoundError("user_not_found", details={"user_email": payload.user_email})
        target_user_id = user.id

    if not target_user_id:
        raise BadRequestError("user_id_or_user_email_required")
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
    )
    return NotificationOut.model_validate(record)
